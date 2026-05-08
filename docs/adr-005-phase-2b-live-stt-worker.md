# ADR 005: Phase 2B Live STT Worker and First Production Model

Date: 2026-05-08

## Status

Accepted.

## Context

Phase 2A created deterministic VAD-derived utterance windows, a provider-neutral STT interface, the
`mlx_whisper` adapter, and `uv run benchmark-stt`. The next risk was moving from offline artifacts to
live transcription without putting model inference back into the audio queue-drain loop.

## Decision

Use `mlx_whisper` with `mlx-community/whisper-large-v3-turbo` as the first live STT provider. Keep
`mlx-community/whisper-tiny` for smoke tests and fast artifact validation only.

Implement live STT as a separate worker:

- `EndpointingConsumer` may call a lightweight chunk handler and endpoint handler.
- The chunk handler stores recent PCM chunks in a bounded live buffer.
- The endpoint handler converts finalized speech-end events into STT jobs.
- The STT worker drains its own queue and runs provider inference outside the audio queue-drain loop.
- The worker is disabled by default and enabled with `PROOF_STT_ENABLED=true`.

## Implementation

- `backend/audio/live_stt.py` defines `AudioWindowBuffer`, `LiveSttOrchestrator`, worker stats, live
  jobs, and recent transcript storage.
- The live worker prepares MLX models inside the same worker thread that runs transcription so
  thread-local MLX GPU stream state is valid during inference.
- `backend/audio/consumer.py` accepts a `chunk_handler` in addition to the existing endpoint handler.
- `backend/main.py` owns the live STT orchestrator in FastAPI lifespan, includes `stt_worker` in
  `/health`, and exposes `/api/stt`.
- `backend/config.py` adds live STT settings: provider, model, language, queue depth, buffer history,
  pre-roll, and post-roll.
- `backend/audio/stt.py` supports direct `transcribe_audio(...)` calls for live PCM jobs.
- `.env.example`, `README.md`, and `AGENTS.md` document the live worker and selected model.

## Benchmark Evidence

Large-v3-turbo smoke:

- Command: `uv run benchmark-stt --vad-provider silero_onnx --stt-provider mlx_whisper --model-id mlx-community/whisper-large-v3-turbo --input-glob '.data/audio/0a764bab-00c0-41e8-986f-cdfd434b3509_first_30s.wav' --limit-segments 1`
- Result: 1 window, 22.23 s speech, 20.83 s initial model load, 1.61 s STT wall time, RTF 0.0723,
  zero errors.
- Artifact: `docs/benchmarks/phase-2b-stt-silero-mlx-large-v3-turbo-smoke-2026-05-08.md`.

Large-v3-turbo 20-window benchmark:

- Command: `uv run benchmark-stt --vad-provider silero_onnx --stt-provider mlx_whisper --model-id mlx-community/whisper-large-v3-turbo --limit-segments 20`
- Result: 20 windows, 85.46 s speech, 0.94 s cached model load, 19.07 s STT wall time, RTF 0.2231,
  p50/p95 window wall time 0.7906/0.9414 s, zero empty transcripts, zero errors.
- Artifact: `docs/benchmarks/phase-2b-stt-silero-mlx-large-v3-turbo-20-2026-05-08.md`.

## Verification

- `uv run ruff check .`
- `uv run mypy .`
- `uv run pytest` passed with 22 tests.
- Unit coverage includes live endpoint-to-STT job processing with the fake provider and API health
  exposure for `/api/stt`.
- Backend smoke with
  `PROOF_BACKEND_PORT=8020 PROOF_STT_ENABLED=true PROOF_STT_PROVIDER=fake PROOF_VAD_PROVIDER=rms uv run backend`
  showed `/health` and `/api/stt` reporting `stt_worker.enabled=true`, `running=true`, provider
  `fake`, model load time `0.0`, and zero queued jobs/errors.
- Full-stack WebSocket smoke on port 8021 sent synthetic speech plus trailing silence through
  `/ws/audio`; `/api/stt` reported `enqueued_jobs=1`, `completed_transcripts=1`,
  `processing_errors=0`, and a recent fake transcript for the finalized RMS endpoint window.
- Production-provider WebSocket replay smoke on port 8024 used
  `PROOF_STT_PROVIDER=mlx_whisper`, `PROOF_STT_MODEL=mlx-community/whisper-large-v3-turbo`, and
  `PROOF_VAD_PROVIDER=silero_onnx` against a 30-second captured WAV. `/api/stt` reported
  `enqueued_jobs=1`, `completed_transcripts=1`, `processing_errors=0`, model load time 0.91 s, STT
  wall time 1.19 s, `speaker=Speaker_1`, and a non-empty final transcript.

## Consequences

- Live transcription can now be enabled without blocking capture ingestion.
- Model load can still affect backend startup when STT is enabled with a real model. This is
  acceptable for the POC and visible in `/health` and `/api/stt`.
- The next Phase 2 step is diarization and transcript publishing to the extension UI.
