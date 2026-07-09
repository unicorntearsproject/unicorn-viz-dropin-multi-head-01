"""Multi-head display controller.

This module encapsulates monitor discovery, display-mode policy (single/span/mirror)
and staged shared-frame readback buffers. Mirror-mode presentation is GL-native
tile-blitting done by the main app (single window, no per-display SDL windows);
see MATE-X11-MULTIHEAD-NOTES.md for why an earlier per-window approach was
abandoned.
"""
from __future__ import annotations

import logging
from typing import Any

import moderngl
import sdl2

from unicornviz.config import Config

log = logging.getLogger(__name__)

DROPIN_CAPABILITIES = {
    'name': 'multihead',
    'class_symbol': 'MultiHeadController',
}


class MultiHeadController:
    """Own multi-monitor policy, mirror outputs, and shared readback buffers."""

    DISPLAY_MODES: tuple[str, ...] = (
        'single',
        'span_included',
        'span_all',
        'mirror_included',
        'mirror_all',
    )
    DISPLAY_MODE_ALIASES: dict[str, str] = {
        'span': 'span_included',
        'mirror': 'mirror_included',
    }

    HELP_ENTRIES: list[tuple[str, str, str]] = [
        ('Display Modes', 'x', 'Single display'),
        ('Display Modes', 'Shift+X', 'Cycle display modes'),
        ('Display Modes', 'Ctrl+X', 'Span included displays'),
        ('Display Modes', 'Ctrl+Shift+X', 'Span all displays'),
        ('Display Modes', 'Alt+X', 'Mirror included displays'),
        ('Display Modes', 'Alt+Shift+X', 'Mirror all displays'),
    ]

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._display_index_requested = int(cfg.get('window', 'display_index', default=0))
        self._display_index = 0
        self._display_mode_requested = str(cfg.get('window', 'display_mode', default='single')).lower()
        self._display_mode = 'single'
        self._excluded_display_indices = self._parse_excluded_display_indices(
            cfg.get('window', 'exclude_display_indices', default=[])
        )
        self._display_layouts_all: list[tuple[int, int, int, int]] = []
        self._display_layouts: list[tuple[int, int, int, int]] = []
        self._active_display_indices: list[int] = []
        self._readback_pbos: list[moderngl.Buffer] = []
        self._readback_index = 0
        self._readback_primed = False
        self._readback_size = 0
        self._readback_fallback_logged = False

    def _parse_excluded_display_indices(self, raw: Any) -> set[int]:
        """Parse config into a set of raw SDL display indices to exclude."""
        if raw in (None, '', [], (), set()):
            return set()
        values: list[Any]
        if isinstance(raw, (list, tuple, set)):
            values = list(raw)
        elif isinstance(raw, str):
            values = [part.strip() for part in raw.split(',') if part.strip()]
        else:
            values = [raw]

        parsed: set[int] = set()
        for value in values:
            try:
                parsed.add(int(value))
            except (TypeError, ValueError):
                log.warning('Ignoring invalid window.exclude_display_indices entry: %r', value)
        return {idx for idx in parsed if idx >= 0}

    def _refresh_active_layouts(self) -> None:
        """Refresh the layout set used by span/mirror operations."""
        use_filtered = self._display_mode in {'span_included', 'mirror_included'} and bool(self._excluded_display_indices)
        if not use_filtered:
            self._active_display_indices = list(range(len(self._display_layouts_all)))
            self._display_layouts = list(self._display_layouts_all)
            return

        active_items = [
            (idx, layout)
            for idx, layout in enumerate(self._display_layouts_all)
            if idx not in self._excluded_display_indices
        ]
        if not active_items:
            log.warning(
                'window.exclude_display_indices removed every display for %s; ignoring excludes',
                self._display_mode,
            )
            self._active_display_indices = list(range(len(self._display_layouts_all)))
            self._display_layouts = list(self._display_layouts_all)
            return

        self._active_display_indices = [idx for idx, _layout in active_items]
        self._display_layouts = [layout for _idx, layout in active_items]

    def _active_layout_items(self) -> list[tuple[int, int, int, int, int]]:
        """Return (display_index, x, y, w, h) tuples for active span/mirror displays."""
        return [
            (idx, x, y, w, h)
            for idx, (x, y, w, h) in zip(self._active_display_indices, self._display_layouts, strict=False)
        ]

    @property
    def requested_mode(self) -> str:
        return self._display_mode_requested

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @property
    def display_index(self) -> int:
        return self._display_index

    @property
    def display_layouts(self) -> list[tuple[int, int, int, int]]:
        """Return cached display layouts (x, y, w, h) per SDL display index."""
        return list(self._display_layouts)

    def mirror_layout(self, window_origin_x: int, window_origin_y: int) -> list[tuple[int, int, int, int]]:
        """Return per-display rects translated to window-local coordinates.

        Used by the GL-native mirror path: the main window spans all displays,
        and each display's region is a viewport within that spanned canvas.
        """
        rects: list[tuple[int, int, int, int]] = []
        for x, y, w, h in self._display_layouts:
            rects.append((x - window_origin_x, y - window_origin_y, w, h))
        return rects

    def log_video_displays(self, width: int, height: int) -> int:
        """Log visible SDL displays and return detected display count."""
        count = int(sdl2.SDL_GetNumVideoDisplays())
        self._display_layouts_all = []
        self._display_layouts = []
        self._active_display_indices = []
        if count <= 0:
            log.warning('SDL reported no video displays; defaulting to display 0')
            self._display_layouts_all = [(0, 0, width, height)]
            self._refresh_active_layouts()
            return 1
        for idx in range(count):
            bounds = sdl2.SDL_Rect()
            if sdl2.SDL_GetDisplayBounds(idx, bounds) == 0:
                self._display_layouts_all.append((bounds.x, bounds.y, bounds.w, bounds.h))
                log.info(
                    'Display %d: origin=(%d,%d) size=%dx%d',
                    idx,
                    bounds.x,
                    bounds.y,
                    bounds.w,
                    bounds.h,
                )
        self._refresh_active_layouts()
        if self._excluded_display_indices and self._display_mode in {'span_included', 'mirror_included'}:
            log.info(
                'Excluding displays from %s: %s',
                self._display_mode,
                ', '.join(str(idx) for idx in sorted(self._excluded_display_indices)),
            )
        return count

    def resolve_display_mode(self) -> str:
        """Resolve the configured display mode against supported values."""
        alias = self.DISPLAY_MODE_ALIASES.get(self._display_mode_requested)
        if alias is not None:
            log.info(
                'Normalizing legacy display_mode=%r -> %s',
                self._display_mode_requested,
                alias,
            )
            self._display_mode_requested = alias
        allowed = set(self.DISPLAY_MODES)
        if self._display_mode_requested not in allowed:
            log.warning(
                'Requested display_mode=%r is invalid; using single',
                self._display_mode_requested,
            )
            self._display_mode = 'single'
            return self._display_mode
        self._display_mode = self._display_mode_requested
        return self._display_mode

    def supported_display_modes(self) -> tuple[str, ...]:
        """Return the full list of runtime-supported display modes."""
        return self.DISPLAY_MODES

    def resolve_display_index(self, width: int, height: int) -> int:
        """Resolve configured display index against available SDL displays."""
        count = self.log_video_displays(width, height)
        if self._display_index_requested < 0 or self._display_index_requested >= count:
            if self._display_mode in {'span_included', 'span_all'}:
                log.debug(
                    'Requested display_index=%d is out of range in span mode; using display 0 for restore position',
                    self._display_index_requested,
                )
            else:
                log.warning(
                    'Requested display_index=%d is out of range; using display 0',
                    self._display_index_requested,
                )
            self._display_index = 0
            return self._display_index
        self._display_index = self._display_index_requested
        return self._display_index

    def display_bounds(self, display_index: int, width: int, height: int) -> sdl2.SDL_Rect | None:
        """Return display bounds for selected SDL display, if available."""
        if 0 <= display_index < len(self._display_layouts_all):
            x, y, w, h = self._display_layouts_all[display_index]
            bounds = sdl2.SDL_Rect()
            bounds.x = x
            bounds.y = y
            bounds.w = w
            bounds.h = h
            return bounds
        bounds = sdl2.SDL_Rect()
        if sdl2.SDL_GetDisplayBounds(display_index, bounds) != 0:
            log.warning(
                'SDL_GetDisplayBounds failed for display %d: %s',
                display_index,
                sdl2.SDL_GetError().decode(),
            )
            return None
        return bounds

    def all_display_bounds(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Return union bounds of all visible SDL displays."""
        if not self._display_layouts:
            return 0, 0, width, height
        min_x = min(layout[0] for layout in self._display_layouts)
        min_y = min(layout[1] for layout in self._display_layouts)
        max_x = max(layout[0] + layout[2] for layout in self._display_layouts)
        max_y = max(layout[1] + layout[3] for layout in self._display_layouts)
        return min_x, min_y, max_x - min_x, max_y - min_y

    def window_position_for_display(self, display_index: int, width: int, height: int) -> tuple[int, int]:
        """Compute startup window coordinates centered on selected display."""
        bounds = self.display_bounds(display_index, width, height)
        if bounds is None:
            return sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED
        x = bounds.x + max(0, (bounds.w - width) // 2)
        y = bounds.y + max(0, (bounds.h - height) // 2)
        return x, y

    def move_window_to_display(self, window, width: int, height: int) -> None:
        """Move existing SDL window according to current display mode policy."""
        if window is None:
            return
        if self._display_mode in {'span_included', 'span_all'}:
            x, y, w, h = self.all_display_bounds(width, height)
            sdl2.SDL_SetWindowPosition(window, x, y)
            sdl2.SDL_SetWindowSize(window, w, h)
            return
        x, y = self.window_position_for_display(self._display_index, width, height)
        sdl2.SDL_SetWindowPosition(window, x, y)

    def rebuild_multihead_outputs(self, width: int, height: int) -> int:
        """Refresh display topology after SDL display events."""
        self.log_video_displays(width, height)
        if self._display_index_requested < 0 or self._display_index_requested >= len(self._display_layouts_all):
            self._display_index = 0
        else:
            self._display_index = self._display_index_requested
        return self._display_index

    def release_readback_pbos(self) -> None:
        """Release async readback buffers."""
        for pbo in self._readback_pbos:
            pbo.release()
        self._readback_pbos.clear()
        self._readback_index = 0
        self._readback_primed = False
        self._readback_size = 0

    def ensure_readback_pbos(self, ctx: moderngl.Context, size: int) -> None:
        """Create or resize readback buffers used for shared frame capture."""
        if len(self._readback_pbos) == 2 and self._readback_size == size:
            return
        self.release_readback_pbos()
        self._readback_pbos = [ctx.buffer(reserve=size), ctx.buffer(reserve=size)]
        self._readback_size = size

    def read_shared_frame(self, ctx: moderngl.Context, width: int, height: int) -> bytes | None:
        """Capture one shared frame for recording/mirror using staged readback."""
        size = width * height * 4
        self.ensure_readback_pbos(ctx, size)
        if len(self._readback_pbos) != 2:
            return None
        write_idx = self._readback_index
        read_idx = 1 - write_idx
        try:
            ctx.screen.read_into(self._readback_pbos[write_idx], components=4, alignment=1)
            frame: bytes | None = None
            if self._readback_primed:
                frame = self._readback_pbos[read_idx].read()
            else:
                self._readback_primed = True
            self._readback_index = read_idx
            return frame
        except Exception as exc:
            # Some drivers/backends intermittently fail buffer mapping.
            # Fall back to direct read to keep mirror mode alive.
            if not self._readback_fallback_logged:
                log.warning('Mirror readback fallback active after PBO failure: %s', exc)
                self._readback_fallback_logged = True
            self._readback_primed = False
            self._readback_index = 0
            return ctx.screen.read(components=4, alignment=1)
