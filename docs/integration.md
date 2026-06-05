# multi-head-01 Integration

Owner: Drop-in Maintainers
Status: active
Last updated: 2026-06-05

## Purpose

Describe integration with the app window lifecycle and downstream consumers.

## Integration Points

- Loaded as a subsystem via drop-in symbol loading.
- Owns display discovery, mode policy resolution, and mirror-output lifecycle.
- Provides shared-frame readback buffers used by downstream subsystems.
- First adopter of the new drop-in self-registration API surface in this repo.
	The migration validated the registration flow and is treated as a successful
	baseline for additional subsystem drop-ins.

## Downstream Consumers

- streaming-01 relies on frame readback path for RTMP encoding input.
- Core overlays/rendering use resolved display layout and mode state.

## Performance Notes

- Mirror path uses staged PBO readback to reduce GPU stalls.
- Shared texture upload is reused across mirror windows each frame.

## Deferred Issue

- Span-mode scaling/alignment drift remains open and is intentionally deferred
	for a dedicated follow-up fix pass.

## Related Docs

- ../README.md
- operations.md
- configuration.md
- troubleshooting.md
