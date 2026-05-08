# ADR 003: Phase 2 STT and VAD Benchmark Plan

Date: 2026-05-08

## Status

Accepted. Queue consumer implemented on 2026-05-08. VAD benchmark plan approved on 2026-05-08.

## Context

Phase 1 now has multiple real Google Meet capture sessions with backend telemetry and WAV dumps. The telemetry baseline shows zero dropped chunks across the captured sessions and low backend receive latency, so Phase 2 can start from the existing stream rather than revisiting capture.

Available compute:

- Primary MacBook: Apple M4, 48 GB unified memory.
- Secondary Mac Mini: Apple M4, 64 GB unified memory.

The project target remains local-first real-time processing, with cloud STT/TTS as fallback when it materially improves POC velocity.

## Decision

Use a staged Phase 2 rollout:

1. Keep the new RMS endpoint detector as the deterministic baseline for replay and live plumbing.
2. Implement a backend-managed consumer task that continuously drains `AudioStreamManager.queue`.
3. Add a proper VAD adapter next, starting with Silero or an MLX-compatible equivalent.
4. Add offline replay benchmarks over `.data/audio/*_first_3600s.wav` before attaching model inference to the live WebSocket path.
5. Benchmark local Whisper/MLX transcription on the Mac Mini first, because the 64 GB memory ceiling leaves more room for larger models and concurrent diarization experiments.
6. Keep the MacBook available for capture, extension UI work, and backend control-plane testing.

## Success Metrics

- Capture transport remains at zero sequence drops during replay-backed development.
- VAD endpointing produces stable utterance boundaries on the existing sessions with minimal short false starts.
- First STT benchmark reports real-time factor, wall-clock transcription time, rough segment latency, and a sample transcript artifact for each captured session.
- Live Phase 2 integration only starts after offline replay confirms the selected model can run comfortably faster than real time on at least one local machine.

## Notes

The current RMS endpoint detector is not the final VAD. It is useful because it is deterministic, fast, and works from telemetry alone. It lets us compare future Silero/MLX endpointing against a known baseline.

Verification on 2026-05-08 found that the existing backend on `127.0.0.1:8000` was healthy but had `audio_queue_depth: 512`, the configured queue cap. A fresh backend on `8011` started with `audio_queue_depth: 0`. Synthetic audio still ingested with 0 sequence drops because the manager drops the oldest queued event when the queue is full, but this confirms a live consumer is required before Phase 2 STT/VAD can observe the full stream. See `docs/benchmarks/phase-2-verification-2026-05-08.md`.

## Consumer Implementation Instructions

The next Phase 2 implementation should add a small audio consumer before adding model inference:

1. Create an `AudioConsumer` or `EndpointingConsumer` owned by `backend.main` lifespan.
2. Start it on backend startup with `asyncio.create_task(...)`; stop it cleanly on shutdown.
3. Read from `manager.queue` in a loop with `await manager.queue.get()`, call `queue.task_done()` in a `finally` block, and never block ingestion on STT or LLM work.
4. Run `RmsEndpointDetector.process(event)` inside the first version of the consumer.
5. Publish endpoint events to an internal queue, in-memory ring buffer, or lightweight stats object. Do not wire heavy STT directly into the drain loop; schedule heavier work separately so the queue keeps draining.
6. Track health counters: consumed chunks, endpoint events, last consumed timestamp, processing errors, and current queue depth.
7. Expose those counters in `/health` or a dedicated `/api/audio/consumer` endpoint.
8. Add tests that prove the consumer drains the queue, emits endpoint events, handles cancellation, and keeps running after a malformed or failing event handler.
9. Keep the queue overflow behavior in `AudioStreamManager` for capture resilience, but make sustained non-zero queue depth a health warning once the consumer exists.

## Implementation Result

Implemented `EndpointingConsumer` in `backend/audio/consumer.py` on 2026-05-08. It is owned by the FastAPI lifespan, drains `AudioStreamManager.queue`, runs `RmsEndpointDetector`, stores recent endpoint events, exposes health counters in `/health` and `/api/audio/consumer`, and has tests for draining, endpoint emission, cancellation, and handler error recovery.

Live smoke on `PROOF_BACKEND_PORT=8012` with `uv run send-test-audio --url ws://127.0.0.1:8012/ws/audio --duration-s 2` showed all 10 chunks consumed, `audio_queue_depth: 0`, `processing_errors: 0`, and ack-time `queued_chunks: 1`.

## VAD Benchmark Plan

Decision: the next implementation pass is VAD benchmark and live VAD demonstration only. STT is explicitly out of scope for this pass.

Chosen defaults:

- First benchmark machine: MacBook M4 with 48 GB RAM.
- First real VAD provider: Silero ONNX.
- Baseline/fallback provider: existing RMS endpointing.
- Runtime default: `PROOF_VAD_PROVIDER=rms`; opt into Silero with `PROOF_VAD_PROVIDER=silero_onnx`.

Required implementation:

1. Add a provider-neutral VAD interface with `name`, `process(AudioChunkEvent)`, `flush(session_id)`, and latest frame stats.
2. Wrap current RMS endpointing as the baseline provider without changing its endpoint behavior.
3. Add `SileroOnnxVadDetector` for 16 kHz mono PCM using Python 3.13-compatible `silero-vad[onnx-cpu]` and `onnxruntime`.
4. Add `uv run benchmark-vad` to replay `.data/audio/*_first_3600s.wav` captures and compare RMS versus Silero ONNX.
5. Report per-session/provider duration, wall time, real-time factor, segment count, speech duration, speech ratio, starts per minute, segment duration stats, processing errors, and RMS comparison deltas.
6. Wire configured VAD into `EndpointingConsumer`; keep STT and heavy work off the queue-drain loop.
7. Extend `/health`, `/api/audio/consumer`, and extension Consumer panel with VAD provider, last speech probability when available, and VAD processing error count.
8. Update README, AGENTS.md, and benchmark docs with results and next STT handoff.

Agent task breakdown:

- **VAD Abstraction Agent**: implement interface + RMS wrapper, preserving current behavior with tests.
- **Silero ONNX Agent**: add dependencies, implement adapter, and add import/model-load smoke coverage.
- **Replay Benchmark Agent**: implement `benchmark-vad`, stdlib WAV replay, Markdown/JSON output, and benchmark report generation.
- **Live Wiring + GUI Agent**: configure provider selection, wire live consumer, and update API/UI fields.
- **Documentation Agent**: record results and hand off to STT benchmarking.

Required verification:

- `uv run ruff check .`
- `uv run mypy .`
- `uv run pytest`
- `uv run benchmark-vad --provider rms --provider silero_onnx --output docs/benchmarks/phase-2-vad-benchmark-YYYY-MM-DD.md`
- `cd extension && npm run typecheck && npm run lint && npm run build`
- Live smoke with `PROOF_VAD_PROVIDER=rms` and `PROOF_VAD_PROVIDER=silero_onnx`.

## VAD Benchmark and Live Integration Result

Implemented on 2026-05-08.

- Provider abstraction: `backend/audio/vad.py` defines `VadProvider`, `VadFrameStats`,
  `RmsVadProvider`, `SileroOnnxVadProvider`, and `create_vad_provider`.
- RMS behavior: the existing `RmsEndpointDetector` is wrapped unchanged as the baseline/fallback.
- Silero ONNX: `silero-vad[onnx-cpu]` and `onnxruntime` are pinned in `pyproject.toml`/`uv.lock`.
  The provider accepts the live 16 kHz mono PCM chunks and internally frames them into the
  512-sample windows required by the ONNX model.
- Runtime config: `PROOF_VAD_PROVIDER` defaults to `rms`; `silero_onnx` is opt-in.
- Live consumer: `EndpointingConsumer` uses the configured provider, keeps STT/model handoff out of
  the queue-drain loop, and tracks both total processing errors and VAD processing errors.
- API/UI: `/health`, `/api/audio/consumer`, and the extension Consumer panel expose selected VAD
  provider, latest speech probability when available, and VAD error count.
- Benchmark command: `uv run benchmark-vad` replays `.data/audio/*_first_3600s.wav` and writes
  Markdown plus optional JSON.

MacBook benchmark over 8 local captures, 3879.20 seconds total:

| Provider | Wall s | RTF | Segments | Speech s | Speech ratio | Starts/min | p50 s | p95 s | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RMS | 0.22 | 0.0001 | 365 | 2572.60 | 66.32% | 5.95 | 4.20 | 23.40 | 0 |
| Silero ONNX | 10.53 | 0.0027 | 344 | 2582.53 | 66.57% | 5.49 | 4.22 | 27.90 | 0 |

Compared with RMS, Silero ONNX emitted 21 fewer segments and 9.93 additional seconds of total
speech. This is a good first-pass result for STT handoff because it remains far faster than real
time with no processing errors and appears to reduce short endpoint splits.

Verification completed:

- `uv run ruff check .`
- `uv run mypy .`
- `uv run pytest`
- `uv run benchmark-vad --provider rms --provider silero_onnx --output docs/benchmarks/phase-2-vad-benchmark-2026-05-08.md --json-output docs/benchmarks/phase-2-vad-benchmark-2026-05-08.json`
- `cd extension && npm run typecheck`
- `cd extension && npm run lint`
- `cd extension && npm run build`
- Live smoke with `PROOF_VAD_PROVIDER=rms` on port 8012: 10 synthetic chunks consumed, queue depth
  0, processing errors 0, VAD errors 0.
- Live smoke with `PROOF_VAD_PROVIDER=silero_onnx` on port 8013: 10 synthetic chunks consumed,
  queue depth 0, processing errors 0, VAD errors 0, speech probability exposed.
- Live smoke with `PROOF_VAD_PROVIDER=silero_onnx` on port 8014 and a 150-chunk replay from
  `.data/audio/28b11907-34cb-4a7b-a1b9-35e5732ffd1e_first_3600s.wav`: 150 chunks consumed, queue
  depth 0, 9 endpoint events, processing errors 0, VAD errors 0.

Next STT handoff:

1. Use benchmarked VAD endpoint events to define utterance windows over the captured WAV sessions.
2. Run offline STT benchmarks on those windows before any live STT integration.
3. Keep live STT inference scheduled outside the consumer drain loop so `AudioStreamManager.queue`
   remains real-time.
