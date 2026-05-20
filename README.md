# multi-head-01 — Multi-Head Display Controller

A system drop-in for [unicorn-viz](https://github.com/iDoMeteor/unicorn-viz).

## Description

This is a **subsystem drop-in**, not a visual effect. It provides all multi-monitor functionality: display topology discovery, window placement policy, mirror output management, and staged PBO-based shared-frame readback. It is loaded automatically by `App` at startup.

## Display Modes

- `single`: render on one display selected by `display_index`
- `span_all`: one window stretched across the combined bounds of all included displays
- `mirror_all`: one logical canvas mirrored across all included displays

`span_all` and `mirror_all` are most reliable on **X11**. On Wayland compositors, explicit window placement may be ignored by design. Unicorn Viz automatically attempts an X11 fallback when a multi-head mode is requested and Wayland is the active driver.

If `exclude_display_indices` is unset or empty, all multi-head behavior remains exactly as before. When set, only `span_all` and `mirror_all` ignore those raw SDL display indices; `single` mode still uses the full display list and `display_index` semantics do not change.

## Config

```toml
[window]
display_mode  = "single"   # single | span_all | mirror_all
display_index = 0          # raw SDL display index for single mode selection
exclude_display_indices = [0]  # optional: omit displays from span_all / mirror_all only
```

## Architecture Notes

- `MultiHeadController` is loaded via `unicornviz.dropins.load_dropin_symbol`.
- Mirror windows share the main GL context through a shared SDL GL context.
- Frame readback uses double-buffered PBOs to minimise GPU stalls.
- Mirror texture uploads happen once per frame; all mirror windows share the same GPU texture.

## Tags

Subsystem — not discoverable as a playlist effect.
