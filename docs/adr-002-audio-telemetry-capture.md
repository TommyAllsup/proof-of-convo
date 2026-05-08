# ADR 002: Audio Telemetry Capture

Date: 2026-05-05

## Status

Accepted for Phase 1.

## Context

The Phase 1 backend previously saved optional WAV debug audio and surfaced chunk health metrics
only in memory and over WebSocket acknowledgements. That made post-session analysis difficult:
latency, dropped chunk, audio level, queue depth, and session metadata disappeared when the session
ended.

Telemetry must be enabled by default for POC learning, but it also needs a clear off switch because
meeting metadata and timing can be sensitive.

## Decision

Persist audio telemetry as separate sidecar files under `.data/telemetry/`:

- `<session_id>_session.json` stores session metadata and final aggregate stats.
- `<session_id>_chunks.jsonl` stores one chunk-health event per line.

The backend has a global feature flag:

- `PROOF_TELEMETRY_ENABLED=true`
- `PROOF_TELEMETRY_DIR=.data/telemetry`

The extension has a per-session **Telemetry capture** setting. It defaults on and is included in
`session_start` as `telemetry_enabled`. Backend telemetry is written only when both the global
backend flag and the per-session extension flag are enabled.

## Consequences

- WAV capture and telemetry capture are independent.
- Disabling telemetry in the extension affects new capture sessions, not an already-running session.
- JSONL is easy to append, inspect with shell tools, and later import into benchmarks or dashboards.
- Chunk telemetry does not include raw PCM payloads; audio remains in the WAV dump path.

## Follow-Ups

- Add latency summary generation from JSONL files after more real Meet sessions.
- Include STT and diarization events in the same session directory once Phase 2 lands.
