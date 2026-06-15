# ADR 007: Phase 3 TTS and Virtual Mic Voice Injection

Date: 2026-05-08

## Status

Accepted for POC.

## Context

Phase 3 needs a path from agent text to audible meeting speech without blocking Phase 2 audio
ingestion or STT. The POC should support high-realism cloud TTS while remaining testable on machines
without API keys, BlackHole, or a configured Google Meet microphone.

## Decision

- Add a backend-managed `TtsOrchestrator` with its own async queue and worker.
- Keep TTS disabled by default with `PROOF_TTS_ENABLED=false`.
- Add a deterministic fake provider for tests and smoke checks.
- Define the initial voice persona as a concise meeting colleague: clear enunciation, moderate pace,
  professional warmth, and restrained expressiveness. ElevenLabs requests apply conservative
  per-request voice settings; other providers inherit the selected voice ID/model until
  provider-specific controls are added.
- Add provider adapters for:
  - ElevenLabs HTTP streaming via `/v1/text-to-speech/:voice_id/stream`.
  - Cartesia WebSocket TTS with raw `pcm_s16le` output.
- Request raw PCM16 audio by default (`pcm_24000`) so chunks can be written directly to
  `sounddevice.RawOutputStream`.
- Use `NullAudioPlayer` when `PROOF_TTS_PLAYBACK_ENABLED=false`; use `SoundDeviceAudioPlayer`
  against the configured output device when playback is enabled.
- Target BlackHole by default through `PROOF_TTS_OUTPUT_DEVICE=BlackHole`, but expose
  `/api/audio/devices` so the user can inspect the exact local PortAudio device names and indices.
- Add `/api/tts` for health and recent speech results, and `/api/tts/speak` for manual utterance
  injection.
- Add `/api/tts/interrupt` for explicit user stop/mute control.
- Add optional per-speech WAV dumps with `PROOF_TTS_DUMP_ENABLED=true`, so provider output can be
  inspected before opening a device or joining a meeting.
- Add a Voice card to the extension so manual speech can be triggered and stopped from the
  popup/sidebar.
- Add `uv run test-tts-playback` for local fake/provider playback smoke checks before joining a
  meeting.
- Add `uv run verify-phase3` for a repeatable preflight over macOS, PortAudio output devices,
  BlackHole/Homebrew cask state, dump directory writability, and provider credentials.
- Treat live `speech_start` endpoint events as barge-in signals. The TTS worker closes playback,
  stops writing the current provider stream at the next chunk boundary, and records the speech as
  interrupted.

## Consequences

- Phase 3 can be validated without cloud calls by running fake TTS with null playback.
- Real voice injection requires local macOS audio routing that automated tests cannot fully verify.
- The first implementation supports mid-stream interruption at provider chunk boundaries. Smooth
  fade-out and provider-specific cancellation messages remain future work.
- Provider/player failures are captured as worker stats instead of crashing the backend lifespan.

## Local Test Protocol

1. Run `uv run check-audio-devices` or call `/api/audio/devices` to confirm a BlackHole output
   device is visible.
2. Run `uv run verify-phase3 --device BlackHole`; use `--strict` when the machine is expected to be
   fully configured.
3. Start the backend with fake TTS and null playback:
   `PROOF_TTS_ENABLED=true PROOF_TTS_PROVIDER=fake PROOF_TTS_PLAYBACK_ENABLED=false uv run backend`.
4. POST to `/api/tts/speak` and verify `/api/tts` reports one completed speech, non-zero audio bytes,
   and zero processing errors.
5. Optionally set `PROOF_TTS_DUMP_ENABLED=true` and verify the recent speech includes a `.data/tts`
   WAV path.
6. Run `uv run test-tts-playback --provider fake --device BlackHole` and verify the audio reaches
   the virtual device.
7. Start the backend with ElevenLabs or Cartesia plus `PROOF_TTS_PLAYBACK_ENABLED=true` and
   `PROOF_TTS_OUTPUT_DEVICE=BlackHole`.
8. In Google Meet settings, select BlackHole as the microphone.
9. Trigger a short manual utterance from the extension Voice card and verify another participant or
   second Meet client hears it clearly without local speaker echo.

## Follow-ups

- Add provider-specific cancellation messages and smooth playback fade-out for interruption.
- Add provider-specific latency benchmarks with a real account and selected voice.
- Add a richer debug artifact manifest with provider request metadata and subjective listening notes.
