# Phase 1 Synthetic Smoke Benchmark

Date: 2026-05-05

## Environment

- macOS on Apple Silicon.
- Python: CPython 3.13.12 via `uv`.
- MLX check: `Device(gpu, 0)`.
- Backend command: `PROOF_AUDIO_DUMP_SECONDS=1 uv run backend`.
- Synthetic sender: `uv run send-test-audio --duration-s 1 --chunk-ms 200`.

## Result

- Health endpoint: `{"ok": true, "service": "proof-of-convo-backend", "active_sessions": 0, "audio_queue_depth": 0}`.
- Session ack returned a debug WAV path under `.data/audio/`.
- Chunks sent: 5.
- Total samples: 16,000.
- Dropped chunks: 0.
- RMS: ~0.2475 for the synthetic sine wave.
- Peak: ~0.3500.
- Reported chunk latencies: ~0.14 ms to ~0.76 ms on local loopback.

## Notes

- This verifies the backend WebSocket, binary packet parser, PCM16-to-float32 conversion, audio level computation, session stats, and WAV dump path.
- This is not a substitute for the manual Google Meet 10-minute soak test in `docs/phase-1-testing.md`; that still needs real Chrome/Meet audio and participant speech.

