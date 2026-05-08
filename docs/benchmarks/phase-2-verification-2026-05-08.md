# Phase 2 Verification Run

Date: 2026-05-08

## Commands

Backend gates:

```bash
uv run ruff check .
uv run mypy .
uv run pytest
```

Extension gates:

```bash
cd extension
npm run typecheck
npm run lint
npm run build
```

Telemetry and backend smoke:

```bash
uv run analyze-telemetry --threshold 0.012 --silence-ms 500 --min-speech-ms 250
uv run backend
curl -sS http://127.0.0.1:8000/health
lsof -nP -iTCP:8000 -sTCP:LISTEN
uv run send-test-audio --duration-s 2
PROOF_BACKEND_PORT=8011 uv run backend
curl -sS http://127.0.0.1:8011/health
```

## Results

- `ruff`, `mypy`, and `pytest` passed. Test suite result: 9 passed.
- Extension `typecheck`, `lint`, and production `build` passed.
- Telemetry replay completed and reproduced the capture baseline:
  - `28b11907`: 21.6 min, 6,479 chunks, 0 drops, latency p50/p95/max 1.3/1.9/8.5 ms.
  - `2fab3853`: 23.5 min, 7,064 chunks, 0 drops, latency p50/p95/max 1.3/2.2/7.1 ms.
  - `f819e6b7`: 2.2 min, 668 chunks, 0 drops, latency p50/p95/max 1.4/1.9/2.5 ms.
- `uv run backend` could not bind to `127.0.0.1:8000` because existing Python backend processes were already listening on that port.
- The existing `8000` backend responded to `/health`, but reported `audio_queue_depth: 512`.
- A fresh backend on `8011` started cleanly and reported `audio_queue_depth: 0`.
- `uv run send-test-audio --duration-s 2` against the existing `8000` backend completed with 10 chunks, 0 sequence drops, and sub-millisecond backend receive latency.

## Finding

The current `AudioStreamManager.queue` is a bounded handoff point for Phase 2 consumers, but no long-lived consumer drains it yet. Once the queue reaches `PROOF_AUDIO_QUEUE_MAX` (default `512`), `AudioStreamManager.ingest_packet()` keeps capture live by dropping the oldest queued event and inserting the newest event. This preserves WebSocket responsiveness and telemetry accuracy, but it means a downstream STT/VAD consumer added later will only see recent chunks if the queue has already saturated.

## Recommendation

Implement a backend-managed audio consumer task before attaching STT inference to live capture. The first consumer should drain `manager.queue`, run endpoint detection, publish lightweight endpoint events, and expose health counters. This gives Phase 2 a stable real-time processing loop and prevents queue saturation from hiding downstream lag.
