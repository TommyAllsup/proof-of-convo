from __future__ import annotations

import numpy as np

from backend.audio.diarization import HeuristicSpeakerDiarizer
from backend.audio.stt_windows import UtteranceWindow


def test_heuristic_speaker_diarizer_returns_stable_speaker_for_similar_audio() -> None:
    diarizer = HeuristicSpeakerDiarizer()
    window = _window("w1")
    audio = np.full(3200, 0.1, dtype=np.float32)

    first = diarizer.assign(window=window, audio=audio)
    second = diarizer.assign(window=_window("w2"), audio=audio)

    assert first.speaker == "Speaker_1"
    assert second.speaker == "Speaker_1"
    assert second.confidence >= 0.25


def _window(window_id: str) -> UtteranceWindow:
    return UtteranceWindow(
        window_id=window_id,
        session_id="session-1",
        source_wav="live://session-1",
        sample_rate=16_000,
        vad_provider="rms",
        start_ms=0.0,
        end_ms=200.0,
        duration_ms=200.0,
        padded_start_ms=0.0,
        padded_end_ms=300.0,
        padded_duration_ms=300.0,
        start_sequence=0,
        end_sequence=1,
        peak=0.1,
        mean_rms=0.1,
    )
