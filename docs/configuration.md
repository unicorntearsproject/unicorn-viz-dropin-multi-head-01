# multi-head-01 Configuration

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

## Purpose

Reference for multi-head display policy keys.

## Config Block

```toml
[window]
display_mode = "single"         # single | span_all | mirror_all
display_index = 0
exclude_display_indices = [0]    # optional, span/mirror only
```

## Key Notes

- `exclude_display_indices` applies to `span_all` and `mirror_all` only.
- `single` mode still uses full display list semantics.
- If excludes remove all displays, controller falls back to using all displays.

## Related Docs

- ../README.md
- operations.md
- integration.md
- troubleshooting.md
