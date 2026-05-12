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

## Legacy approach (kept for reference / fallback testing)

`MultiHeadController.create_mirror_outputs()` and friends still exist and can
create per-display SDL windows with a software renderer + ABGR8888 streaming
texture, fed by a PBO-backed readback of the main framebuffer. They are no
longer invoked by `App._create_mirror_outputs()` (now a no-op).

Known issues with the legacy approach:

- On X11 GNOME / MATE / KDE: secondary windows go black or freeze after the
  first frame. PBO `read_into` may stall when other windows pump frames.
- On Windows 11: same symptom; mirror windows show a black frame and the app
  hangs/crashes shortly after.
- Window-event spam (`HIDDEN`/`EXPOSED`) used to cause recreate-storms; that
  was patched but did not fix the underlying GL+multi-window stall.

If anyone needs to revisit: revert `App._create_mirror_outputs()` from the
no-op stub to call `self._multihead.create_mirror_outputs(...)`, keep
`need_frame_for_mirror` enabled, and the legacy SDL_Renderer path still works
end-to-end as previously committed (commit `569d426` in `multi-head-01`).

## Alternative approaches considered (not implemented)

1. Shared GL context across multiple SDL windows (`SDL_GL_SHARE_WITH_CURRENT_CONTEXT`)
   - Pros: each mirror window owns a real GL context, can blit a shared texture
     directly without readback.
   - Cons: SDL2 + moderngl shared contexts are platform-dependent; Wayland
     compositor restrictions, NVIDIA/Intel driver quirks. Significantly more
     code, harder to debug.

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
