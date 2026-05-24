# multi-head-01 Integration

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-05-24

## Purpose

Describe integration with the app window lifecycle and downstream consumers.

## Integration Points

- Loaded as a subsystem via drop-in symbol loading.
- Owns display discovery, mode policy resolution, and mirror-output lifecycle.
- Provides shared-frame readback buffers used by downstream subsystems.

## Downstream Consumers

- streaming-01 relies on frame readback path for RTMP encoding input.
- Core overlays/rendering use resolved display layout and mode state.

## Performance Notes

- Mirror path uses staged PBO readback to reduce GPU stalls.
- Shared texture upload is reused across mirror windows each frame.

## Related Docs

- ../README.md
- operations.md
- configuration.md
- troubleshooting.md
