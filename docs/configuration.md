# multi-head-01 Configuration

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-06-05

## Purpose

Reference for multi-head display policy keys.

## Config Block

```toml
[window]
display_mode = "single"         # single | span_included | span_all | mirror_included | mirror_all
display_index = 0
exclude_display_indices = [0]    # optional, *_included modes only
```

## Key Notes

- `display_mode` supports: `single`, `span_included`, `span_all`,
  `mirror_included`, `mirror_all`.
- Legacy aliases are accepted: `span` -> `span_included`,
  `mirror` -> `mirror_included`.
- `exclude_display_indices` applies to `span_included` and `mirror_included` only.
- `single` mode still uses full display list semantics.
- `span_all` and `mirror_all` always use all detected displays.
- If excludes remove all displays in an included-mode, the controller falls
  back to using all displays.

## Related Docs

- ../README.md
- operations.md
- integration.md
- troubleshooting.md
