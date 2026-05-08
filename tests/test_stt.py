from __future__ import annotations

from backend.audio.stt import FakeSttProvider, MlxWhisperSttProvider
from backend.audio.stt_windows import UtteranceWindow


def test_fake_stt_provider_transcribes_window() -> None:
    window = _window(source_wav="missing.wav")
    transcript = FakeSttProvider().transcribe(window)

    assert transcript.provider == "fake"
    assert transcript.error is None
    assert window.window_id in transcript.text


def test_mlx_whisper_provider_records_read_errors_without_raising() -> None:
    window = _window(source_wav="missing.wav")
    transcript = MlxWhisperSttProvider(model_id="mlx-community/whisper-tiny").transcribe(window)

    assert transcript.provider == "mlx_whisper"
    assert transcript.text == ""
    assert transcript.error is not None
    assert "FileNotFoundError" in transcript.error


def _window(*, source_wav: str) -> UtteranceWindow:
    return UtteranceWindow(
        window_id="window-1",
        session_id="session-1",
        source_wav=source_wav,
        sample_rate=16_000,
        vad_provider="rms",
        start_ms=0.0,
        end_ms=200.0,
        duration_ms=200.0,
        padded_start_ms=0.0,
        padded_end_ms=200.0,
        padded_duration_ms=200.0,
        start_sequence=0,
        end_sequence=0,
        peak=0.1,
        mean_rms=0.05,
    )
