# MATE / X11 Multi-Head Notes

Date: 2026-05-12

## Problem observed

On Fedora 44 with MATE, multi-head configuration changes could not move the app off the monitor that launched it. This was reproducible across multiple `display_mode` / `display_index` combinations.

## Likely root cause

MATE uses an X11 compositor/window-manager path that is less forgiving than GNOME Wayland for startup placement and fullscreen hints.

The previous code path relied on `SDL_WINDOW_FULLSCREEN_DESKTOP` for fullscreen-on-one-monitor behavior. On some X11 WMs, that can cause the window manager to pin the window to the launching display or ignore placement hints until after the window is mapped.

## Short-term support lift

Implemented short-term mitigation in `unicornviz/app.py`:

- Detect MATE-like sessions from `XDG_CURRENT_DESKTOP`, `XDG_SESSION_DESKTOP`, or `DESKTOP_SESSION`.
- Use borderless fullscreen windowing instead of SDL desktop fullscreen when MATE is detected.
- Keep existing desktop fullscreen behavior for other environments.

Estimated lift:

- Runtime fix: low, already implemented.
- Validation on MATE: moderate. Needs an actual MATE/X11 test on multi-monitor hardware to confirm placement hints and span/mirror behavior.
- Future hardening: moderate. If MATE still ignores placement in a specific mode, add explicit post-create verification and a fallback windowed/borderless mode selector.

## Recommended next test

On the MATE box, validate:

1. `display_mode = "single"` with `fullscreen = true`.
2. `display_mode = "span_all"` with `fullscreen = true`.
3. `display_mode = "mirror_all"` with `fullscreen = false` and `true`.

If any mode still sticks to the launch monitor, we should add a user-facing `window.fullscreen_mode` override and make the WM/session-specific fallback explicit.
