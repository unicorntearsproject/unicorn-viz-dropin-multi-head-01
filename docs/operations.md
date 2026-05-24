# multi-head-01 Operations

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

## Purpose

Operational runbook for display topology and mirror/span behavior.

## Startup Checklist

1. Set `[window] display_mode` (`single`, `span_all`, `mirror_all`).
2. Set `display_index` for `single` mode selection.
3. Optionally set `exclude_display_indices` for span/mirror modes.
4. Start Unicorn Viz and verify display topology in logs.

## Mode Behavior

- `single`: one display selected by raw SDL display index.
- `span_all`: one canvas across included displays.
- `mirror_all`: mirrored output across included displays.

## Operator Guidance

- Prefer X11 fallback for strict multi-head placement behavior.
- Use display excludes to reserve an operator/tools monitor.
- Validate layout after compositor or GPU-driver changes.

## Related Docs

- ../README.md
- configuration.md
- integration.md
- troubleshooting.md
