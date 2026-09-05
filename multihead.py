"""Multi-head display controller.

This module encapsulates monitor discovery, display-mode policy (single/span/mirror)
and staged shared-frame readback buffers. Mirror-mode presentation is GL-native
tile-blitting done by the main app (single window, no per-display SDL windows);
see MATE-X11-MULTIHEAD-NOTES.md for why an earlier per-window approach was
abandoned.
"""
from __future__ import annotations

__version__ = '1.1.0-rc.2'

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

    def __init__(self, cfg: Config, runtime_excludes: 'list[int] | None' = None) -> None:
        self._cfg = cfg
        self._display_index_requested = int(cfg.get('window', 'display_index', default=0))
        self._display_index = 0
        self._display_mode_requested = str(cfg.get('window', 'display_mode', default='single')).lower()
        self._display_mode = 'single'
        # ``runtime_excludes`` is the operator's monitor-editor choice persisted
        # by control-room-01 under ``multihead.monitor_editor.exclude_display_
        # indices`` in the runtime store. When present it *replaces* the
        # config.toml list (same override-else-config rule the editor itself
        # uses to seed its checkboxes). Before 1.1.0 nothing ever read that
        # key, so "Monitor excludes saved (restart required)" never did
        # anything -- the 2026-09-05 multi-head audit's #1 finding.
        self._excludes_source = 'config'
        if isinstance(runtime_excludes, list):
            self._excluded_display_indices = self._parse_excluded_display_indices(runtime_excludes)
            self._excludes_source = 'runtime'
        else:
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
        self._vj_api: Any = None
        # Displays page (docs/planning/control-room-drop-in-integration-plan-
        # 2026-09-05.md P3): a *staged* copy of the excludes, seeded from
        # whatever's active at construction. Editing this never touches
        # _excluded_display_indices/live layouts -- same "restart required"
        # contract the old control-room-01 monitor editor had -- only
        # save_pending_excludes() persists it, for the NEXT launch to pick up
        # via runtime_excludes above.
        self._pending_excluded_display_indices: set[int] = set(self._excluded_display_indices)
        self._page_selected_idx = 0

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
    def excluded_display_indices(self) -> set[int]:
        """Raw SDL display indices excluded from *_included modes (a copy)."""
        return set(self._excluded_display_indices)

    @property
    def excludes_source(self) -> str:
        """``'runtime'`` when the monitor editor's saved list is in force, else ``'config'``."""
        return self._excludes_source

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

    def all_detected_displays(self) -> list[tuple[int, int, int, int, int]]:
        """Return every SDL-detected display as (index, x, y, w, h).

        A live query (like ``log_video_displays``, not a cached read of
        ``_display_layouts_all``) so the Displays page reflects a hot-plugged
        monitor without needing a restart to see it in the map/list, even
        though *acting* on the change still needs one (excludes are a
        next-launch preference, not live -- see ``_pending_excluded_display_
        indices``).
        """
        displays: list[tuple[int, int, int, int, int]] = []
        count = max(1, int(sdl2.SDL_GetNumVideoDisplays()))
        for idx in range(count):
            bounds = sdl2.SDL_Rect()
            if sdl2.SDL_GetDisplayBounds(idx, bounds) != 0:
                continue
            displays.append((idx, int(bounds.x), int(bounds.y), int(bounds.w), int(bounds.h)))
        return displays

    @property
    def pending_excluded_display_indices(self) -> set[int]:
        """Staged excludes edited by the Displays page (a copy)."""
        return set(self._pending_excluded_display_indices)

    def toggle_pending_exclude(self, display_index: int) -> bool:
        """Flip one display's staged exclude state; returns the new state."""
        if display_index in self._pending_excluded_display_indices:
            self._pending_excluded_display_indices.remove(display_index)
            return False
        self._pending_excluded_display_indices.add(display_index)
        return True

    def reset_pending_excludes(self) -> None:
        """Discard staged edits, reverting to config.toml's exclude list."""
        self._pending_excluded_display_indices = self._parse_excluded_display_indices(
            self._cfg.get('window', 'exclude_display_indices', default=[])
        )

    def save_pending_excludes(self) -> list[int]:
        """Persist the staged excludes for the next launch to pick up.

        Writes the same runtime-store key ``runtime_excludes`` reads at
        construction, so SAVE here plus a restart is the whole round trip.
        """
        indices = sorted(int(i) for i in self._pending_excluded_display_indices)
        setter = getattr(self._vj_api, 'set_runtime_state', None)
        if callable(setter):
            setter('multihead.monitor_editor.exclude_display_indices', indices)
        return indices

    def set_vj_api(self, api: Any) -> None:
        """Inject the VJApi instance after construction (app.py builds this
        controller before vj_api exists -- see runtime_excludes in __init__).

        Registers the Displays page (docs/planning/control-room-drop-in-
        integration-plan-2026-09-05.md P3): retires control-room-01's
        hardcoded DISPLAY panel and monitor-editor modal.
        """
        self._vj_api = api
        register = getattr(api, 'register_operator_page', None)
        if not callable(register):
            return
        try:
            from unicornviz.operator_panels import OperatorPage  # noqa: PLC0415
            register(OperatorPage(
                name='displays',
                title='Displays',
                owner='multi-head-01',
                draw=self._draw_displays_page,
                on_action=self._displays_page_action,
            ))
        except Exception as exc:
            log.debug('multi-head-01: Displays page registration failed: %s', exc)

    def shutdown(self) -> None:
        """Unregister the Displays page (operator_panels.py "Lifecycle")."""
        unregister = getattr(self._vj_api, 'unregister_operator_page', None)
        if callable(unregister):
            try:
                unregister('displays')
            except Exception:
                pass

    _MODE_LABELS: dict[str, str] = {
        'single': 'SINGLE',
        'span_included': 'SPAN INCL',
        'span_all': 'SPAN ALL',
        'mirror_included': 'MIRROR INCL',
        'mirror_all': 'MIRROR ALL',
    }
    _MODE_BEHAVIOR: dict[str, str] = {
        'single': 'Single display only; excludes have no effect.',
        'span_included': 'Spans only included displays; excludes are active.',
        'span_all': 'Spans every detected display; excludes are ignored.',
        'mirror_included': 'Mirrors only included displays; excludes are active.',
        'mirror_all': 'Mirrors every detected display; excludes are ignored.',
    }

    def _draw_button(
        self, canvas: Any, rect: tuple[int, int, int, int], label: str,
        action: str, payload: Any, *, active: bool = False, accent: 'tuple[int, int, int] | None' = None,
    ) -> None:
        """Small local button primitive -- PanelCanvas gives raw draw/theme/
        fonts, not CR's own private _draw_button, so tier-2 pages draw their
        own (module docstring "Declarative first" -- draw is the escape hatch
        for surfaces content/buttons can't express)."""
        draw, theme = canvas.draw, canvas.theme
        bx, by, bw, bh = rect
        tone = accent or theme.accent
        fill = tone + (90,) if active else theme.panel_alt + (255,)
        outline = tone if active else theme.line
        draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=8, fill=fill, outline=outline + (255,), width=1)
        font = canvas.fonts['small']
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        draw.text((bx + max(4, (bw - tw) // 2), by + max(2, (bh - th) // 2) - tb[1]), label, font=font, fill=theme.text)
        canvas.add_hotspot(action, payload, (bx, by, bw, bh))

    def _draw_displays_page(self, canvas: Any) -> None:
        """Tier-2 draw for the 'displays' page: mode buttons, a display map,
        list, and include/exclude/save controls. Replaces control-room-01's
        hardcoded DISPLAY panel and monitor-editor modal (same operator
        capability, now owned here instead of a duck-typed reach into this
        controller from CR)."""
        draw, theme = canvas.draw, canvas.theme
        x, y, w, h = canvas.rect
        small, heading = canvas.fonts['small'], canvas.fonts['heading']

        displays = self.all_detected_displays()
        self._page_selected_idx = max(0, min(self._page_selected_idx, len(displays) - 1)) if displays else 0
        active_mode = self.display_mode
        modes = list(self.supported_display_modes()) or ['single']
        if 'single' not in modes:
            modes.insert(0, 'single')
        pending = self._pending_excluded_display_indices
        include_filters = active_mode in {'span_included', 'mirror_included'}

        mode_gap = 10
        mode_bw = max(110, (w - mode_gap * (len(modes) - 1)) // len(modes))
        for idx, mode in enumerate(modes):
            self._draw_button(
                canvas, (x + idx * (mode_bw + mode_gap), y, mode_bw, 32),
                self._MODE_LABELS.get(mode, mode.upper()), 'mode', mode, active=active_mode == mode,
            )

        map_y = y + 32 + 16
        controls_h = 96
        map_h = max(120, h - (map_y - y) - controls_h - 16)
        map_w = int(w * 0.6)
        map_rect = (x, map_y, map_w, map_h)
        mx, my, mw_, mh_ = map_rect
        draw.rounded_rectangle((mx, my, mx + mw_, my + mh_), radius=12, fill=theme.panel_alt + (255,), outline=theme.line + (255,), width=1)

        if displays:
            min_x = min(d[1] for d in displays)
            min_y = min(d[2] for d in displays)
            max_x = max(d[1] + d[3] for d in displays)
            max_y = max(d[2] + d[4] for d in displays)
            world_w = max(1, max_x - min_x)
            world_h = max(1, max_y - min_y)
            scale = min((mw_ - 24) / world_w, (mh_ - 24) / world_h)
            off_x = mx + 12 + int(((mw_ - 24) - world_w * scale) * 0.5)
            off_y = my + 12 + int(((mh_ - 24) - world_h * scale) * 0.5)
            for list_idx, (did, dx, dy, dw, dh) in enumerate(displays):
                rx = off_x + int((dx - min_x) * scale)
                ry = off_y + int((dy - min_y) * scale)
                rw = max(36, int(dw * scale))
                rh = max(28, int(dh * scale))
                is_selected = list_idx == self._page_selected_idx
                is_excluded = did in pending
                is_effectively_excluded = include_filters and is_excluded
                base = theme.danger if is_effectively_excluded else theme.success
                fill = base + (95 if is_selected else 55,)
                outline = theme.accent if is_selected else base
                draw.rounded_rectangle((rx, ry, rx + rw, ry + rh), radius=8, fill=fill, outline=outline + (255,), width=2)
                draw.text((rx + 8, ry + 6), f'D{did}  {dw}x{dh}', font=small, fill=theme.text)
                if is_effectively_excluded:
                    draw.text((rx + 8, ry + rh - 18), 'EXCLUDED', font=small, fill=theme.warn)
                canvas.add_hotspot('select', list_idx, (rx, ry, rw, rh))
        else:
            tb = draw.textbbox((0, 0), 'No displays detected', font=heading)
            draw.text(
                (mx + max(0, (mw_ - (tb[2] - tb[0])) // 2), my + max(0, (mh_ - (tb[3] - tb[1])) // 2)),
                'No displays detected', font=heading, fill=theme.text_dim,
            )

        list_x = mx + mw_ + 16
        list_w = max(1, x + w - list_x)
        draw.rounded_rectangle((list_x, map_y, list_x + list_w, map_y + map_h), radius=12, fill=theme.panel_alt + (255,), outline=theme.line + (255,), width=1)
        draw.text((list_x + 12, map_y + 10), 'DISPLAY LIST', font=small, fill=theme.text_dim)
        row_y = map_y + 34
        for idx, (did, dx, dy, dw, dh) in enumerate(displays[:16]):
            if row_y + 24 > map_y + map_h - 4:
                break
            is_selected = idx == self._page_selected_idx
            tag = 'EXCLUDED' if did in pending else 'INCLUDED'
            fill = theme.accent + (52,) if is_selected else theme.panel + (200,)
            draw.rounded_rectangle((list_x + 8, row_y - 2, list_x + list_w - 8, row_y + 22), radius=8, fill=fill, outline=theme.line + (255,), width=1)
            draw.text((list_x + 14, row_y + 3), f'D{did}  {dw}x{dh} @ ({dx},{dy})  {tag}', font=small, fill=theme.text)
            canvas.add_hotspot('select', idx, (list_x + 8, row_y - 2, list_w - 16, 24))
            row_y += 26

        controls_y = map_y + map_h + 16
        draw.rounded_rectangle((x, controls_y, x + w, y + h), radius=12, fill=theme.panel_alt + (255,), outline=theme.line + (255,), width=1)
        by_ = controls_y + 14
        selected_did = displays[self._page_selected_idx][0] if displays else None
        sel_excluded = selected_did is not None and selected_did in pending
        self._draw_button(
            canvas, (x + 16, by_, 190, 30), 'INCLUDE' if sel_excluded else 'EXCLUDE',
            'toggle_exclude', None, accent=theme.success if sel_excluded else theme.warn,
        )
        self._draw_button(canvas, (x + 216, by_, 140, 30), 'RESET', 'reset_excludes', None)
        self._draw_button(canvas, (x + 366, by_, 170, 30), 'SAVE', 'save_excludes', None, accent=theme.success)
        behavior = self._MODE_BEHAVIOR.get(active_mode, '')
        draw.text((x + 16, by_ + 42), f'Mode: {active_mode} -- {behavior}', font=small, fill=theme.text_dim)
        draw.text((x + 16, by_ + 62), 'Saved excludes apply on next launch.', font=small, fill=theme.warn)

    def _displays_page_action(self, action: str, payload: Any) -> str | None:
        """Control Room buttons -> the same set_display_mode() the mode
        hotkeys use, plus the staged-exclude editing verbs above."""
        if action == 'mode':
            if self._vj_api is None:
                return None
            mode = self._vj_api.set_display_mode(str(payload))
            return f'Display mode: {mode}'
        if action == 'select':
            self._page_selected_idx = max(0, int(payload))
            return None
        if action == 'toggle_exclude':
            displays = self.all_detected_displays()
            if not displays:
                return 'No displays detected'
            sel = max(0, min(self._page_selected_idx, len(displays) - 1))
            did = int(displays[sel][0])
            excluded = self.toggle_pending_exclude(did)
            return f'Display {did}: {"excluded" if excluded else "included"}'
        if action == 'reset_excludes':
            self.reset_pending_excludes()
            return 'Monitor excludes reset'
        if action == 'save_excludes':
            self.save_pending_excludes()
            return 'Monitor excludes saved (restart required)'
        return None

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
