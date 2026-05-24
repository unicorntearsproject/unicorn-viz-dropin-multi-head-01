# multi-head-01 Troubleshooting

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

## Purpose

Troubleshooting guide for display topology and mirroring behavior.

## Common Issues

### Display mode ignored on Wayland

- Some compositors ignore explicit window placement by design.
- Retry on X11 when strict multi-head control is required.

### Wrong monitor selected in single mode

- Confirm raw SDL `display_index` from startup logs.
- Adjust index and retest.

### Reserved operator display still mirrors content

- Confirm `display_mode` is `span_all` or `mirror_all`.
- Confirm `exclude_display_indices` uses raw SDL display numbers.

### Mirror performance is poor

- Reduce render resolution scale.
- Reduce mirror display count where possible.

## Deferred Debug Instrumentation (Keep for JIC)

If mirror or HUD placement regressions reappear during display hot-plug testing,
add a temporary on-screen debug readout showing:

- current `display_mode`
- current `_display_index`
- current window origin + size (`_window_origin_x/_window_origin_y`, `_window_width/_window_height`)
- active mirror rect list (`_mirror_rects`)
- computed primary overlay viewport (`_primary_display_viewport()`)

Reason: this makes stale topology/viewport drift obvious immediately after
`SDL_DISPLAYEVENT_CONNECTED` / `SDL_DISPLAYEVENT_DISCONNECTED`, without needing
external logs.

## Related Docs

- ../README.md
- operations.md
- configuration.md
- integration.md
