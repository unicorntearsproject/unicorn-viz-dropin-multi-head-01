# MATE / X11 Multi-Head Notes

Date: 2026-05-12

## Update: GL-native mirror_all (current approach)

### Iteration 2 (post-validation refinement)

Validation on Fedora 37/GNOME after iteration 1 showed:
- `mirror_all` worked correctly when toggled while NOT fullscreen.
- `mirror_all` toggled while fullscreen left the window pinned at one display
  (`window=1920x1080` instead of `1920x2160`), so one tile-blit rect landed
  offscreen → "half-screen-band" appearance. Fixed by adding explicit
  `mirror_all` handling to the `set_display_mode` fullscreen branch.
- After running through Image Showcase and Video Showcase effects, the mirror
  display occasionally collapsed to "half-screen on both monitors". Root
  cause: webcam overlay and HUD render after `_render` returns, painting
  directly to the bound framebuffer at logical (1920×1080) viewport. With
  the previous design, `_render` had already done the tile-blit and left the
  spanned window's framebuffer bound, so HUD/webcam landed only on the
  bottom-left quadrant of the spanned canvas.
- Win11 / Fedora 44/MATE crashed with
  `MultiHeadController object has no attribute 'display_layouts'` because
  their drop-in submodule pointer pre-dated the new `display_layouts`
  property/method on the controller.

### Iteration 2 fixes

1. Compose-then-tile pipeline. In mirror mode, `_render` now writes the
   final per-display image into `_fbo_a` and leaves it bound at logical
   viewport. The main loop renders webcam and HUD overlays into that same
   FBO, then performs one tile-blit at the end of the frame. This keeps
   webcam/HUD on every display.
2. Backward-compatible accessors. `App._multihead_layouts()` and
   `App._multihead_mirror_layout()` use `getattr` to fall back to the
   controller's private `_display_layouts` attribute and to derive rects
   manually if the public helpers are missing. This unblocks runs against
   older drop-in submodule pointers (no immediate `git submodule update`
   required to avoid the crash).
### Iteration 1 background

The previous SDL mirror implementation (per-display SDL renderer windows) was
tested on Fedora 37/GNOME, Fedora 44/MATE, and Windows 11. It initialized
cleanly (including Mirror frame diagnostics) but then frequently went black,
hung, or crashed. Root-cause analysis pointed at multi-window SDL_Renderer
interaction with the main GL context and readback path.

The current implementation in `unicornviz/app.py` replaces that path with a
**single-window, GL-native mirror**:

1. In `mirror_all`, the SDL window is created spanning all displays
   (borderless, like `span_all`).
2. Effects continue to render at single-display logical resolution into an
   offscreen FBO (`_fbo_a`).
3. Final present uses `_present_mirror_tiled()` which sets the GL viewport to
   each display's region within the spanned window and blits the FBO once per
   region.

Why this is robust:

- One window, one GL context — no multi-window SDL_Renderer fragility.
- No GPU readback (PBO) needed for mirror.
- No SDL_UpdateTexture / SDL_RenderCopy code path on a second window.
- Identical behavior on Wayland, X11 (GNOME, MATE), and Windows.
- Mirror rects are computed by `MultiHeadController.mirror_layout()` and
  recomputed on resize and on runtime mode-switch hotkeys.

## Legacy approach — removed 2026-07-09

`MultiHeadController.create_mirror_outputs()` and friends (`destroy_mirror_outputs`,
`resize_mirror_textures`, `present_mirror_outputs`, `is_mirror_window_id`, the
`_mirror_outputs` list, `has_mirror_outputs`) have been **deleted** from
`multihead.py`, along with their no-op call sites in `unicornviz/app.py`
(`App._create_mirror_outputs()` etc.). They had been dead code (the app-side
methods were already no-ops) since the GL-native tile-blit mirror shipped;
this cleanup removed the dead pathway itself rather than just its callers.

This decision was reconfirmed, not just executed mechanically: a 2026-07-08
platform audit investigating unrelated control-room-01/dj-mixer-01 black-screen
reports on Fedora/GNOME/Wayland considered reviving a per-monitor-window
approach for `mirror_all` (to let GNOME/Mutter suppress its panel, which it
won't do for a borderless spanning window — see
`docs/audits/2026-07-08-render-pipeline-platform-audit.md` §4). That
investigation is what surfaced this exact legacy code and its documented
failure history below, and confirmed it should stay deleted, not resurrected.

Known issues with the legacy approach (why it was abandoned originally):

- On X11 GNOME / MATE / KDE: secondary windows go black or freeze after the
  first frame. PBO `read_into` may stall when other windows pump frames.
- On Windows 11: same symptom; mirror windows show a black frame and the app
  hangs/crashes shortly after.
- Window-event spam (`HIDDEN`/`EXPOSED`) used to cause recreate-storms; that
  was patched but did not fix the underlying GL+multi-window stall.

The full implementation is preserved in git history if ever needed again —
see commit `569d426` in `multi-head-01`, and the pre-removal state at the
commit immediately prior to the 2026-07-09 "clean up dead mirror pathways"
commit. Do not resurrect this specific architecture (CPU readback → PBO →
per-window `SDL_RENDERER_SOFTWARE` streaming texture) without a real fix for
the black-screen/freeze pattern above — that pattern reproduced on three
platforms and was never resolved, it was replaced.

## Alternative approaches considered (not implemented) — for the panel-suppression question, not mirror rendering generally

If per-monitor real windows for `mirror_all`/`span_all` are ever revisited
(e.g. specifically to let the compositor suppress its panel, since a
borderless spanning window can't get real per-output fullscreen state), the
options are, in preference order:

1. **Preferred if revisited: shared GL context across multiple SDL windows**
   (`SDL_GL_SHARE_WITH_CURRENT_CONTEXT`) — each per-monitor window owns a
   real GL context and renders natively, sharing GL resources with the main
   context; no CPU readback needed at all. This is architecturally distinct
   from the removed legacy approach above (which read the framebuffer back
   to the CPU and streamed it into software-rendered windows) and should not
   inherit its failure history automatically — but it's unproven in this
   codebase. Cons: SDL2 + moderngl shared contexts are platform-dependent;
   Wayland compositor restrictions, NVIDIA/Intel driver quirks. Significantly
   more code, harder to debug than the current single-window design.

2. Wayland compositor mirror via wl_output cloning
   - Pros: zero application-side cost.
   - Cons: not user-controllable from the app; requires sway/Hyprland config.

3. External presenters (e.g. Spout/Syphon-style shared memory + helper apps
   per display)
   - Pros: process isolation; one renderer per display.
   - Cons: extra processes; not zero-config; no native Linux equivalent that
     covers all WMs.

## Original MATE/X11 fullscreen placement notes (still valid)

On Fedora 44 with MATE, multi-head configuration changes could not move the
app off the monitor that launched it. This was reproducible across multiple
`display_mode` / `display_index` combinations.

Likely root cause: MATE uses an X11 compositor/window-manager path that is
less forgiving than GNOME Wayland for startup placement and fullscreen hints.
The previous code path relied on `SDL_WINDOW_FULLSCREEN_DESKTOP` for
fullscreen-on-one-monitor behavior. On some X11 WMs, that can cause the
window manager to pin the window to the launching display or ignore placement
hints until after the window is mapped.

Mitigation in `unicornviz/app.py`:

- Detect MATE-like sessions from `XDG_CURRENT_DESKTOP`,
  `XDG_SESSION_DESKTOP`, or `DESKTOP_SESSION`.
- Use borderless fullscreen windowing instead of SDL desktop fullscreen when
  MATE is detected.
- Keep existing desktop fullscreen behavior for other environments.

## Recommended validation matrix

For each platform/WM:

1. `display_mode = "single"` with `fullscreen = true`
2. `display_mode = "span_all"` with `fullscreen = true`
3. `display_mode = "mirror_all"` with `fullscreen = false`
4. `display_mode = "mirror_all"` with `fullscreen = true`
5. Runtime hotkey switching: `X` (config) / `Shift+X` (single) /
   `Ctrl+X` (span) / `Alt+X` (mirror) repeatedly while an effect runs.

Targets: Fedora 37/GNOME, Fedora 44/MATE, Windows 11. If any mode still sticks
to the launch monitor, add an explicit user-facing `window.fullscreen_mode`
override and a per-WM placement fallback chain.
