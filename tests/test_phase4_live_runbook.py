from __future__ import annotations

from scripts.phase4_live_runbook import LiveRunbookConfig, render_runbook


def test_phase4_live_runbook_renders_required_live_validation_steps() -> None:
    markdown = render_runbook(
        LiveRunbookConfig(
            meeting_url="https://meet.google.com/test",
            tester="tester",
            backend_url="http://127.0.0.1:8000",
            backend_host="127.0.0.1",
            backend_port=8000,
            vad_provider="silero_onnx",
            diarization_provider="heuristic_acoustic",
            stt_provider="mlx_whisper",
            stt_model="mlx-community/whisper-large-v3-turbo",
            stt_language="en",
            tts_provider="macos_say",
            tts_model=None,
            tts_voice_name="Erica",
            tts_output_device="BlackHole 2ch",
            preflight_dir=".data/phase4-preflight",
            live_output_dir=".data/phase4-live",
            latency_ms=1500,
        )
    )

    assert "PROOF_STT_ENABLED=true" in markdown
    assert "PROOF_TTS_PLAYBACK_ENABLED=true" in markdown
    assert "PROOF_TTS_OUTPUT_DEVICE=BlackHole 2ch" in markdown
    assert "Set the Google Meet microphone to `BlackHole 2ch`" in markdown
    assert "more realistic audible Meet run" not in markdown
    assert "uv run verify-phase4-live-ready --strict" in markdown
    assert "uv run verify-phase4-live-backend --backend-url http://127.0.0.1:8000 \\" in markdown
    assert "uv run phase4-live-bundle \\" in markdown
    assert "--direct-answer-audible" in markdown
    assert "--no-feedback-loop" in markdown
    assert "another participant hears Erica" in markdown


def test_phase4_live_runbook_warns_for_smoke_test_defaults() -> None:
    markdown = render_runbook(
        LiveRunbookConfig(
            meeting_url="https://meet.google.com/test",
            tester="tester",
            backend_url="http://127.0.0.1:8000",
            backend_host="127.0.0.1",
            backend_port=8000,
            vad_provider="rms",
            diarization_provider="heuristic_acoustic",
            stt_provider="mlx_whisper",
            stt_model="mlx-community/whisper-large-v3-turbo",
            stt_language=None,
            tts_provider="fake",
            tts_model=None,
            tts_voice_name="meeting-agent",
            tts_output_device="BlackHole",
            preflight_dir=".data/phase4-preflight",
            live_output_dir=".data/phase4-live",
            latency_ms=1500,
        )
    )

    assert "more realistic audible Meet run" in markdown
    assert "exact PortAudio output device name" in markdown
    assert "use `silero_onnx`" in markdown
