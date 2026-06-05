# multi-head-01 — Multi-Head Display Controller

A system drop-in for [unicorn-viz](https://github.com/iDoMeteor/unicorn-viz).

## Description

This is a **subsystem drop-in**, not a visual effect. It provides all multi-monitor functionality: display topology discovery, window placement policy, mirror output management, and staged PBO-based shared-frame readback. It is loaded automatically by `App` at startup.

Status note (2026-06-05): multi-head behavior is considered stable and
production-ready for current operator workflows, with one known deferred issue:
span-mode scaling/alignment drift still needs a dedicated follow-up pass.

## Highlight: Include/Exclude Control for Span/Mirror

`multi-head-01` supports explicit included-display and all-display variants
for span/mirror behavior.

This lets you keep one monitor free for operator tools such as a DAW, mixer,
browser, or streaming dashboard while Unicorn Viz spans or mirrors across the
remaining displays.

Example:

```toml
[window]
display_mode = "mirror_included"
display_index = 0
exclude_display_indices = [0]
```

With that config, raw SDL display `0` is left alone and the mirrored show uses
all the other included displays.

## Display Modes

- `single`: render on one display selected by `display_index`
- `span_included`: one window stretched across the combined bounds of included displays
- `span_all`: one window stretched across the combined bounds of all displays
- `mirror_included`: one logical canvas mirrored across included displays
- `mirror_all`: one logical canvas mirrored across all displays
- Alias support: `span` maps to `span_included`, `mirror` maps to
	`mirror_included`.

All span/mirror modes are most reliable on **X11**. On Wayland compositors,
explicit window placement may be ignored by design. Unicorn Viz automatically
attempts an X11 fallback when a multi-head mode is requested and Wayland is
the active driver.

If `exclude_display_indices` is unset or empty, included/all variants behave
the same. When set, only `span_included` and `mirror_included` respect
`exclude_display_indices`. `span_all` and `mirror_all` always use every
detected display. `single` mode still uses the full display list and
`display_index` semantics do not change.

## Config

```toml
[window]
display_mode  = "single"   # single | span_included | span_all | mirror_included | mirror_all
display_index = 0          # raw SDL display index for single mode selection
exclude_display_indices = [0]  # optional: omit displays from *_included modes only
```

If `exclude_display_indices` is unset or empty, included/all variants are
equivalent.

## Architecture Notes

- `MultiHeadController` is loaded via `unicornviz.dropins.load_dropin_symbol`.
- Mirror windows share the main GL context through a shared SDL GL context.
- Frame readback uses double-buffered PBOs to minimise GPU stalls.
- Mirror texture uploads happen once per frame; all mirror windows share the same GPU texture.

## Tags

Subsystem — not discoverable as a playlist effect.

---

## Structured Docs

- docs/operations.md
- docs/configuration.md
- docs/integration.md
- docs/troubleshooting.md
