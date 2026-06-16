# Phase 4 Live Readiness Smoke

Date: 2026-06-15

## Commands

```bash
PROOF_STT_ENABLED=true \
PROOF_STT_PROVIDER=mlx_whisper \
PROOF_TTS_ENABLED=true \
PROOF_TTS_PLAYBACK_ENABLED=true \
PROOF_TTS_OUTPUT_DEVICE="BlackHole 2ch" \
uv run verify-phase4-live-ready --strict
```

```bash
PROOF_BACKEND_PORT=8124 \
PROOF_STT_ENABLED=true \
PROOF_STT_PROVIDER=mlx_whisper \
PROOF_TTS_ENABLED=true \
PROOF_TTS_PLAYBACK_ENABLED=true \
PROOF_TTS_OUTPUT_DEVICE="BlackHole 2ch" \
uv run backend
```

Then:

```bash
curl http://127.0.0.1:8124/health > .data/live-backend-health.json
```

Additional running-backend verifier:

```bash
PROOF_BACKEND_PORT=8125 \
PROOF_STT_ENABLED=true \
PROOF_STT_PROVIDER=mlx_whisper \
PROOF_TTS_ENABLED=true \
PROOF_TTS_PLAYBACK_ENABLED=true \
PROOF_TTS_OUTPUT_DEVICE="BlackHole 2ch" \
uv run backend
```

```bash
uv run verify-phase4-live-backend \
  --backend-url http://127.0.0.1:8125 \
  --expected-output-device "BlackHole 2ch" \
  --strict
```

## Result

- `verify-phase4-live-ready --strict` passed.
- BlackHole was visible to PortAudio as `BlackHole 2ch`.
- Backend started successfully on port `8124`.
- `verify-phase4-live-backend --strict` passed against a live backend on port `8125`.
- `/health` reported:
  - `stt_worker.enabled=true`
  - `stt_worker.running=true`
  - `stt_worker.provider=mlx_whisper`
  - `tts_worker.enabled=true`
  - `tts_worker.running=true`
  - `tts_worker.player=sounddevice`
  - `tts_worker.output_device=BlackHole 2ch`

## Remaining Gap

This smoke proves the pre-Meet backend and audio-device readiness path. It does not prove the Phase
4 live acceptance criteria because no real Google Meet session was active, no remote participant
heard Erica, and no live transcript or TTS evidence bundle was captured from a meeting.
