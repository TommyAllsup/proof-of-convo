# Phase 3 Test Protocol: TTS and Google Meet Voice Injection

Date: 2026-05-08

This protocol verifies Phase 3 from synthesized speech to audible Google Meet participant audio.
Run it after the Phase 1/2 backend and extension flows are already working.

## Preconditions

- macOS on Apple Silicon.
- Chrome extension loaded from `extension/dist`.
- Backend dependencies installed with `uv sync --all-groups`.
- BlackHole or an equivalent virtual audio output/input device installed and visible to PortAudio.
- ElevenLabs or Cartesia credentials for realistic voice testing.

## 1. Verify Local Audio Device Readiness

```bash
uv run verify-phase3 --device BlackHole
uv run check-audio-devices
```

Pass criteria:

- `verify-phase3` reports `virtual mic output device` as `ok`.
- `check-audio-devices` lists a BlackHole output device.

If BlackHole is missing:

```bash
brew install --cask blackhole-2ch
```

Then reboot macOS. The Homebrew cask currently requires a reboot before the driver is visible.

## 2. Verify Provider Streaming Without Audio Device

Fake provider:

```bash
uv run test-tts-playback --provider fake --null
```

ElevenLabs:

```bash
ELEVENLABS_API_KEY=... \
PROOF_TTS_VOICE_ID=... \
uv run test-tts-playback --provider elevenlabs --null
```

Cartesia:

```bash
CARTESIA_API_KEY=... \
PROOF_TTS_VOICE_ID=... \
uv run test-tts-playback --provider cartesia --model-id sonic-3 --null
```

Pass criteria:

- Command prints non-zero `chunks` and `audio_bytes`.
- `ttfa_ms` is present.
- No provider credential or stream errors are raised.

## 3. Verify Local Playback Routing

```bash
uv run test-tts-playback --provider fake --device BlackHole
```

Pass criteria:

- Command completes without `output audio device not found`.
- If BlackHole is monitored in an aggregate/multi-output setup, the test tone is observable only
  through the intended route.

Avoid routing TTS to laptop speakers during meeting tests. Use headphones or BlackHole-only output
to prevent echo.

## 4. Start Backend With Voice Enabled

Fake provider with WAV debug artifacts:

```bash
PROOF_TTS_ENABLED=true \
PROOF_TTS_PROVIDER=fake \
PROOF_TTS_PLAYBACK_ENABLED=true \
PROOF_TTS_OUTPUT_DEVICE=BlackHole \
PROOF_TTS_DUMP_ENABLED=true \
uv run backend
```

ElevenLabs realistic voice:

```bash
PROOF_TTS_ENABLED=true \
PROOF_TTS_PROVIDER=elevenlabs \
PROOF_TTS_MODEL=eleven_flash_v2_5 \
PROOF_TTS_VOICE_ID=... \
ELEVENLABS_API_KEY=... \
PROOF_TTS_PLAYBACK_ENABLED=true \
PROOF_TTS_OUTPUT_DEVICE=BlackHole \
PROOF_TTS_DUMP_ENABLED=true \
uv run backend
```

Cartesia realistic voice:

```bash
PROOF_TTS_ENABLED=true \
PROOF_TTS_PROVIDER=cartesia \
PROOF_TTS_MODEL=sonic-3 \
PROOF_TTS_VOICE_ID=... \
CARTESIA_API_KEY=... \
PROOF_TTS_PLAYBACK_ENABLED=true \
PROOF_TTS_OUTPUT_DEVICE=BlackHole \
PROOF_TTS_DUMP_ENABLED=true \
uv run backend
```

## 5. Verify Backend Voice APIs

```bash
curl http://127.0.0.1:8000/api/tts
curl -X POST http://127.0.0.1:8000/api/tts/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"This is a Proof of Conversation voice routing test.","interrupt":true}'
curl http://127.0.0.1:8000/api/tts
```

Pass criteria:

- `/api/tts` reports `running: true`.
- `completed_speeches` increments.
- `processing_errors` remains `0`.
- `total_audio_bytes` is non-zero.
- When `PROOF_TTS_DUMP_ENABLED=true`, recent speech includes a `dump_path` under `.data/tts`.

## 6. Configure Google Meet

1. Join a test Google Meet from Chrome.
2. Open Meet settings.
3. Set microphone to BlackHole.
4. Keep output/speakers routed to headphones or a non-feedback path.
5. Open the extension popup or sidebar.
6. Confirm the Voice panel reports `running`.

## 7. End-to-End Audible Test

1. Join the same Meet from a second account/device.
2. In the extension Voice panel, enter a short sentence.
3. Click **Speak**.
4. Confirm the second account/device hears the agent clearly.
5. Click **Stop** during a longer utterance and confirm speech stops.
6. Speak as a human while a longer utterance is playing and confirm barge-in interruption occurs.

Pass criteria:

- Other participants hear the agent voice from the Meet participant using the BlackHole mic.
- There is no local speaker feedback or echo.
- `/api/tts` shows non-zero audio bytes, recent speech records, and zero processing errors.
- Manual Stop or human speech can interrupt agent speech.

## Evidence To Capture

- `uv run verify-phase3 --strict --provider elevenlabs` or `--provider cartesia` output.
- `/api/tts` JSON after the manual utterance.
- Generated `.data/tts/*.wav` debug artifact path.
- Short note with provider, voice ID/name, output device, and whether a second participant heard the
  voice clearly.

## Troubleshooting

- `BlackHole not visible`: reinstall the cask and reboot.
- `output audio device not found`: run `uv run check-audio-devices` and set
  `PROOF_TTS_OUTPUT_DEVICE` to the exact visible name or numeric index.
- No audio in Meet: confirm Meet microphone is set to BlackHole, not the physical microphone.
- Echo/feedback: route playback only to BlackHole or use headphones.
- Provider errors: verify API key, voice ID, model ID, and provider quota.
- Distorted audio: keep provider output as PCM16 at `PROOF_TTS_SAMPLE_RATE=24000`; if using another
  format, add explicit decoding/resampling before playback.
