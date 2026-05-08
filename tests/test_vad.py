from __future__ import annotations

import numpy as np
import pytest
import torch

import backend.audio.vad as vad_module
from backend.audio.frames import AudioPacket
from backend.audio.manager import AudioChunkEvent
from backend.audio.vad import SileroOnnxVadProvider


def test_silero_onnx_uses_chunk_clock_for_endpoint_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_model = _FakeSileroModel([0.9, 0.0])
    monkeypatch.setattr(vad_module, "load_silero_vad", lambda *, onnx: fake_model)
    provider = SileroOnnxVadProvider(
        threshold=0.5,
        min_silence_duration_ms=0,
        speech_pad_ms=0,
        min_speech_ms=0.0,
    )

    started = provider.process(_event(sequence=0, capture_started_at_ms=0.0))
    ended = provider.process(_event(sequence=1, capture_started_at_ms=0.0))

    assert started[0].type == "speech_start"
    assert started[0].event_ms == 1_000.0
    assert ended[0].type == "speech_end"
    assert ended[0].event_ms == 1_032.0
    assert ended[0].segment is not None
    assert ended[0].segment.start_ms == 1_000.0
    assert ended[0].segment.end_ms == 1_032.0
    assert fake_model.reset_count == 1


class _FakeSileroModel:
    def __init__(self, probabilities: list[float]) -> None:
        self._probabilities = probabilities
        self._index = 0
        self.reset_count = 0

    def __call__(self, tensor: torch.Tensor, sampling_rate: int) -> torch.Tensor:
        assert len(tensor) == 512
        assert sampling_rate == 16_000
        probability = self._probabilities[min(self._index, len(self._probabilities) - 1)]
        self._index += 1
        return torch.tensor(probability)

    def reset_states(self) -> None:
        self.reset_count += 1


def _event(*, sequence: int, capture_started_at_ms: float) -> AudioChunkEvent:
    sample_rate = 16_000
    sample_count = 512
    chunk_started_at_ms = 1_000.0 + sequence * 32.0
    wave_data = np.full(sample_count, 0.2, dtype=np.float32)
    pcm16 = (wave_data * 32767.0).astype("<i2").tobytes()
    return AudioChunkEvent(
        session_id="session-1",
        packet=AudioPacket(
            sequence=sequence,
            tab_id=1,
            capture_started_at_ms=capture_started_at_ms,
            chunk_started_at_ms=chunk_started_at_ms,
            client_sent_at_ms=chunk_started_at_ms,
            sample_rate=sample_rate,
            sample_count=sample_count,
            pcm16=pcm16,
        ),
        rms=0.2,
        peak=0.2,
        received_at_ms=chunk_started_at_ms,
    )
