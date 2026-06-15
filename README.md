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

Phase 2A offline STT benchmark:

```bash
uv run benchmark-stt --vad-provider silero_onnx \
  --stt-provider mlx_whisper \
  --model-id mlx-community/whisper-tiny \
  --limit-segments 20 \
  --artifact-dir .data/stt/silero-mlx-tiny-20 \
  --output docs/benchmarks/phase-2a-stt-silero-mlx-tiny-20-2026-05-08.md \
  --json-output docs/benchmarks/phase-2a-stt-silero-mlx-tiny-20-2026-05-08.json
```

The command exports VAD-derived utterance windows, per-window transcript JSONL, joined per-session
transcript Markdown, and a benchmark summary. The full local tiny-model benchmark over 8 captures
processed 344 Silero windows and 2719.80 s of speech with 0.69 s model load time and 34.09 s STT
wall time (RTF 0.0125), with zero provider errors. See
`docs/benchmarks/phase-2a-stt-silero-mlx-tiny-full-2026-05-08.md`.

Phase 2B live STT worker:

```bash
PROOF_VAD_PROVIDER=silero_onnx \
PROOF_STT_ENABLED=true \
PROOF_STT_PROVIDER=mlx_whisper \
PROOF_STT_MODEL=mlx-community/whisper-large-v3-turbo \
uv run backend
```

The live worker buffers recent PCM chunks, receives finalized VAD endpoint events, and runs STT in a
separate async worker so model inference never blocks `EndpointingConsumer`. Recent transcripts are
published as final `utterance` records with `Speaker_N` labels from the current heuristic acoustic
diarizer. Worker health and recent utterances are exposed at:

```bash
curl http://127.0.0.1:8000/api/stt
```

`PROOF_STT_ENABLED=false` remains the default. The Phase 2B large-v3-turbo benchmark over 20 Silero
windows processed 85.46 s of speech in 19.07 s STT wall time (RTF 0.2231), with zero errors and zero
empty transcripts. See `docs/benchmarks/phase-2b-stt-silero-mlx-large-v3-turbo-20-2026-05-08.md`.

The extension popup and sidebar poll `/api/stt` and show the recent speaker-attributed transcript
feed when STT is enabled.

Phase 3 manual TTS and virtual mic playback:

```bash
PROOF_TTS_ENABLED=true \
PROOF_TTS_PROVIDER=fake \
PROOF_TTS_PLAYBACK_ENABLED=false \
uv run backend
```

The fake provider verifies the queue, streaming, and stats path without cloud credentials or an audio
device. Set `PROOF_TTS_DUMP_ENABLED=true` to write synthesized PCM to inspectable WAV files under
`.data/tts/`. Status and manual speech APIs:

```bash
curl http://127.0.0.1:8000/api/tts
curl -X POST http://127.0.0.1:8000/api/tts/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"Thanks. I have one clarifying question: what decision do we need before the next step?","interrupt":true}'
curl -X POST http://127.0.0.1:8000/api/tts/interrupt
```

For audible Google Meet injection with fully local macOS speech, install/configure BlackHole, set
Google Meet's microphone to the BlackHole device, then enable playback and the `macos_say`
provider:

```bash
PROOF_TTS_ENABLED=true \
PROOF_TTS_PROVIDER=macos_say \
PROOF_TTS_VOICE_ID=Samantha \
PROOF_TTS_PLAYBACK_ENABLED=true \
PROOF_TTS_OUTPUT_DEVICE="BlackHole 2ch" \
uv run backend
```

The `macos_say` provider uses built-in `say` plus `afconvert`, so it needs no cloud credentials.
ElevenLabs and Cartesia remain available for later voice-quality comparisons. ElevenLabs can be
tested with `PROOF_TTS_PROVIDER=elevenlabs`, `PROOF_TTS_MODEL=eleven_flash_v2_5`, a voice ID, and
`ELEVENLABS_API_KEY`. Cartesia can be tested with `PROOF_TTS_PROVIDER=cartesia`,
`PROOF_TTS_MODEL=sonic-3`, a Cartesia voice ID, and `CARTESIA_API_KEY`. `/api/audio/devices` lists
output devices visible to PortAudio.
The extension popup and sidebar include a **Voice** card with TTS health and a manual **Speak**
button plus **Stop** control for end-to-end voice-routing tests.

Local playback smoke:

```bash
uv run verify-phase3
uv run test-tts-playback --provider fake --null
uv run test-tts-playback --provider macos_say --voice-id Samantha --null
uv run test-tts-playback --provider macos_say --voice-id Samantha --device "BlackHole 2ch"
```

The verifier reports whether BlackHole is visible to PortAudio and whether provider credentials are
present. The first playback command verifies provider streaming without opening an audio device. The
second playback command should be used after BlackHole is installed and visible in
`uv run check-audio-devices`.

Full Google Meet voice-injection verification is documented in
[docs/phase-3-testing.md](docs/phase-3-testing.md).
Current completion evidence and remaining environment blocker are tracked in
[docs/phase-3-completion-audit-2026-05-08.md](docs/phase-3-completion-audit-2026-05-08.md).

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
