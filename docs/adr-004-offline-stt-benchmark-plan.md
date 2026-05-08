# ADR 004: Offline STT Benchmark Before Live Transcription

Date: 2026-05-08

## Status

Accepted. Implemented on 2026-05-08 for the offline benchmark framework, fake provider, and MLX
Whisper adapter. Production model selection remains open.

## Context

Phase 1 capture is stable enough to use as the source for downstream work. Phase 2 now has:

- A backend-owned `EndpointingConsumer` that drains `AudioStreamManager.queue`.
- Provider-neutral VAD plumbing.
- RMS baseline endpointing.
- Silero ONNX endpointing selected by `PROOF_VAD_PROVIDER=silero_onnx`.
- Replay VAD benchmarks over local Google Meet WAV captures.
- Consumer health exposed in `/health`, `/api/audio/consumer`, and the extension Consumer panel.

The next risk is attaching STT too early to the live queue-drain path. STT model load, inference,
chunk overlap, prompt/context reuse, and artifact capture are heavier than VAD and should be
benchmarked offline first.

## Decision

The next phase is **Phase 2A: offline STT benchmark and utterance-window handoff**.

Do not implement live STT streaming, diarization, extension transcript UI, agent brain logic, TTS, or
audio injection in this pass.

Use the existing `.data/audio/*_first_3600s.wav` captures and Silero ONNX VAD endpoint events to cut
utterance windows. Benchmark local STT over those windows, produce transcript artifacts, and choose
the first live STT integration path only after the benchmark passes.

## Required Work

1. Add reusable VAD-to-window extraction.
   - Input: 16 kHz mono PCM16 WAV files and a configured VAD provider.
   - Output: deterministic windows with source file, session id, start/end time, sequence bounds,
     provider name, peak, mean RMS, duration, and `window_id`.
   - Include configurable pre-roll/post-roll padding, clamped to file bounds.
2. Add a provider-neutral STT interface.
   - Capture provider name, model id/version, quantization if any, language if known, wall time,
     transcript text, confidence if available, and errors.
   - Keep this interface independent from FastAPI and `EndpointingConsumer`.
3. Implement the first local STT adapter.
   - Preferred first target is an MLX Whisper path using a `whisper-large-v3-turbo`-class model.
   - A smaller MLX Whisper model is acceptable for the initial smoke if it reduces setup risk.
   - Cloud STT adapters should wait unless local setup is blocked.
4. Add `uv run benchmark-stt`.
   - Suggested arguments: `--vad-provider`, `--stt-provider`, `--input-glob`, `--artifact-dir`,
     `--output`, `--json-output`, `--limit-segments`, and `--max-audio-minutes`.
   - Artifacts: utterance-window JSONL, per-window transcript JSONL, per-session joined transcript
     Markdown, benchmark Markdown, and optional benchmark JSON.
5. Add tests that do not require heavy model execution.
   - Synthetic window extraction.
   - Artifact schema/shape.
   - Fake STT provider success and error cases.
   - Model-backed smoke tests should be explicit commands, not default `pytest`.

## Metrics

Report at minimum:

- Input files and total audio duration.
- VAD provider and STT provider.
- Machine metadata.
- Model id, package version, quantization, language mode, and load time.
- Number of utterance windows.
- Transcribed speech duration.
- STT wall time and real-time factor.
- Per-window p50/p95 wall time.
- Empty transcript rate.
- Processing error count.
- Paths to transcript artifacts.

## Success Criteria

- Existing VAD live-consumer behavior is unchanged.
- Window extraction is deterministic across repeated runs.
- The selected provider runs faster than real time on captured utterance windows, with target full
  benchmark RTF below `0.70`.
- At least one joined transcript artifact is useful for manual meeting-content review before
  diarization.
- Benchmark docs contain enough metadata for another agent to reproduce the result.
- The live STT design remains explicit: endpoint events feed a separate STT worker; heavy model
  inference never runs inside `EndpointingConsumer._consume`.

## Verification

Required local gates:

```bash
uv run ruff check .
uv run mypy .
uv run pytest
uv run benchmark-stt --vad-provider silero_onnx --stt-provider <provider> \
  --limit-segments 20 \
  --output docs/benchmarks/phase-2a-stt-smoke-YYYY-MM-DD.md
uv run benchmark-stt --vad-provider silero_onnx --stt-provider <provider> \
  --output docs/benchmarks/phase-2a-stt-benchmark-YYYY-MM-DD.md \
  --json-output docs/benchmarks/phase-2a-stt-benchmark-YYYY-MM-DD.json
```

## Next Decision

Run a quality-focused benchmark with the intended `whisper-large-v3-turbo`-class MLX model or a
documented replacement, then choose the first live STT worker implementation. The worker must consume
endpoint events from a separate queue and must not run model inference inside
`EndpointingConsumer._consume`.

## Implementation Result

Implemented on 2026-05-08.

- `backend/audio/stt_windows.py` exports deterministic VAD-derived utterance windows from 16 kHz mono
  PCM16 WAV captures, with configurable pre-roll/post-roll padding and JSONL manifest output.
- `backend/audio/stt.py` defines the provider-neutral STT interface, a fake deterministic provider
  for tests/artifact validation, and an `mlx_whisper` adapter using `mlx-whisper`.
- `scripts/benchmark_stt.py` adds `uv run benchmark-stt` with Markdown/JSON benchmark summaries,
  window manifests, per-window transcript JSONL, and joined per-session transcript Markdown.
- `pyproject.toml` now includes `mlx-whisper` and the `benchmark-stt` entrypoint.
- Tests cover deterministic window extraction, JSONL artifacts, fake STT output, MLX adapter error
  recording, and the benchmark artifact path without requiring a heavy model in default `pytest`.

Verification results:

- `uv run ruff check .` passed.
- `uv run mypy .` passed.
- `uv run pytest` passed with 21 tests.
- Fake smoke: `uv run benchmark-stt --vad-provider rms --stt-provider fake --limit-segments 3`
  generated `docs/benchmarks/phase-2a-stt-fake-smoke-2026-05-08.md`.
- MLX tiny one-window smoke with RMS generated
  `docs/benchmarks/phase-2a-stt-mlx-tiny-smoke-2026-05-08.md`.
- MLX tiny one-window smoke with Silero generated
  `docs/benchmarks/phase-2a-stt-silero-mlx-tiny-smoke-2026-05-08.md`.
- MLX tiny 20-window smoke with Silero generated
  `docs/benchmarks/phase-2a-stt-silero-mlx-tiny-20-2026-05-08.md`: 20 windows, 85.46 s speech,
  0.69 s model load time, 2.47 s STT wall time, RTF 0.0289, 0 errors.
- Full MLX tiny benchmark with Silero generated
  `docs/benchmarks/phase-2a-stt-silero-mlx-tiny-full-2026-05-08.md`: 8 files, 344 windows,
  2719.80 s speech, 0.69 s model load time, 34.09 s STT wall time, RTF 0.0125, 11.63% empty
  transcript rate, 0 errors.
