# Proof of Conversation

Proof of Conversation is a proof-of-concept for a live AI meeting participant. The first milestone is reliable Google Meet tab-audio capture from a Chrome extension into a local FastAPI backend with low-latency PCM streaming and observable health metrics.

See [AGENTS.md](AGENTS.md) for the full phased roadmap.

## Current Scope

- Phase 0 bootstrap: Python backend, MV3 Chrome extension, lint/test/CI scaffolding, environment examples, and docs.
- Phase 1 POC: capture the active `meet.google.com` tab, downsample tab audio to 16 kHz mono PCM16 in an offscreen document, stream chunks to `ws://127.0.0.1:8000/ws/audio`, show capture/latency/audio-level status, and optionally write the first 30 seconds to a local WAV for verification.

## Prerequisites

- macOS on Apple Silicon.
- Python 3.12 or 3.13. The repo includes `.python-version` set to 3.13.
- `uv` for Python dependency management.
- Node.js and npm for the Chrome extension.
- Google Chrome 116 or newer for MV3 service worker stream IDs consumed by offscreen documents.

## Backend Quickstart

```bash
cp .env.example .env
uv sync --all-groups
uv run backend
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Synthetic audio test:

```bash
uv run send-test-audio --duration-s 5
```

Capture telemetry baseline:

```bash
uv run analyze-telemetry --output docs/benchmarks/phase-2-capture-telemetry-baseline-2026-05-08.md
```

If `PROOF_AUDIO_DUMP_SECONDS=30`, debug WAV files are written under `.data/audio/`. These files are ignored by git.

Telemetry is enabled by default. Per-session metadata is written to `.data/telemetry/*_session.json`,
and chunk-level audio health metrics are written to `.data/telemetry/*_chunks.jsonl`. Set
`PROOF_TELEMETRY_ENABLED=false` to disable backend telemetry globally, or turn off **Telemetry
capture** in the extension settings to disable it for new capture sessions.

The extension popup and sidebar include a **Consumer** panel that polls
`/api/audio/consumer` from the configured backend URL. Use it to demonstrate Phase 2 queue
consumption:

```bash
uv run backend
uv run send-test-audio --duration-s 5
```

The panel should show consumed chunk count increasing, queue depth returning to `0`, and recent
endpoint events appearing as the RMS endpoint detector observes speech.

Phase 2 VAD provider selection:

```bash
PROOF_VAD_PROVIDER=rms uv run backend
PROOF_VAD_PROVIDER=silero_onnx uv run backend
```

`rms` is the default baseline/fallback. `silero_onnx` uses `silero-vad[onnx-cpu]` and
`onnxruntime` on 16 kHz mono PCM. The Consumer panel and `/health` expose the selected provider,
latest Silero speech probability when available, and VAD error count.

Replay benchmark:

```bash
uv run benchmark-vad --provider rms --provider silero_onnx \
  --output docs/benchmarks/phase-2-vad-benchmark-2026-05-08.md \
  --json-output docs/benchmarks/phase-2-vad-benchmark-2026-05-08.json
```

Latest local result on the MacBook: RMS processed 3879.20 s of captures in 0.22 s
(RTF 0.0001), and Silero ONNX processed the same audio in 10.53 s (RTF 0.0027) with zero
processing errors. See `docs/benchmarks/phase-2-vad-benchmark-2026-05-08.md`.

## Extension Quickstart

```bash
cd extension
npm install
npm run build
```

Load the unpacked extension:

1. Open `chrome://extensions`.
2. Enable Developer Mode.
3. Click **Load unpacked**.
4. Select `extension/dist`.
5. Open a `https://meet.google.com/...` tab.
6. Click the extension action, then click **Start**.

The popup and side panel show backend connection state, capture state, audio levels, chunk latency, and dropped chunk count.

## Phase 1 Test Protocol

See [docs/phase-1-testing.md](docs/phase-1-testing.md).

## Development Gates

```bash
uv run ruff check .
uv run mypy .
uv run pytest

cd extension
npm run lint
npm run typecheck
npm run build
```

## Project Structure

```text
backend/            FastAPI app, audio packet parsing, stream manager
extension/          MV3 Chrome extension built with Vite, React, TypeScript, Tailwind
scripts/            Local verification helpers
tests/              Python unit and integration tests
docs/               ADRs, setup notes, benchmark notes
AGENTS.md           Phased implementation roadmap and project guidance
```
