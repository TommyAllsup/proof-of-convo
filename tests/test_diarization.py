from __future__ import annotations

import numpy as np
import pytest

from backend.audio.diarization import HeuristicSpeakerDiarizer, create_diarization_provider
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
    assert first.provider == "heuristic_acoustic"
    assert first.merge_state == "new"
    assert second.merge_state == "matched"


def test_diarization_provider_factory_supports_single_speaker_labeling() -> None:
    diarizer = create_diarization_provider("single_speaker")
    diarizer.set_speaker_label(session_id="session-1", speaker="Speaker_1", label="Avery")

    attribution = diarizer.assign(window=_window("w1"), audio=np.full(3200, 0.1, dtype=np.float32))

    assert attribution.speaker == "Speaker_1"
    assert attribution.speaker_label == "Avery"
    assert attribution.provider == "single_speaker"
    assert attribution.merge_state == "fixed"


def test_diarization_provider_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported diarization provider"):
        create_diarization_provider("sortformer")


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
