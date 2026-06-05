# multi-head-01 Troubleshooting

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-06-05

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

- Confirm `display_mode` is `span_included` or `mirror_included`.
- Confirm `exclude_display_indices` uses raw SDL display numbers.
- If using `span_all` or `mirror_all`, note that excludes are intentionally ignored.

### Mirror performance is poor

- Reduce render resolution scale.
- Reduce mirror display count where possible.

### Span mode framing/scaling still looks off

- Current status: known open issue (2026-06-05), deferred for dedicated fix pass.
- Symptom: content frame (for example Candy Frame border) can show visible
	offset/scaling drift in some span layouts.
- Workaround: use `mirror_included` / `mirror_all` or `single` for
	presentation-critical runs until span alignment patch lands.

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
