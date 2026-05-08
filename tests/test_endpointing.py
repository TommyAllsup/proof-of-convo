from __future__ import annotations

from backend.audio.endpointing import RmsEndpointDetector
from backend.audio.frames import AudioPacket
from backend.audio.manager import AudioChunkEvent
from backend.audio.vad import RmsVadProvider, create_vad_provider


def _event(sequence: int, rms: float, *, session_id: str = "session-1") -> AudioChunkEvent:
    sample_rate = 16_000
    sample_count = 3200
    return AudioChunkEvent(
        session_id=session_id,
        packet=AudioPacket(
            sequence=sequence,
            tab_id=1,
            capture_started_at_ms=0.0,
            chunk_started_at_ms=sequence * 200.0,
            client_sent_at_ms=sequence * 200.0,
            sample_rate=sample_rate,
            sample_count=sample_count,
            pcm16=b"\0" * sample_count * 2,
        ),
        rms=rms,
        peak=rms * 2,
        received_at_ms=sequence * 200.0,
    )


def test_rms_endpoint_detector_emits_speech_start_and_end() -> None:
    detector = RmsEndpointDetector(
        speech_rms_threshold=0.01,
        silence_ms=400.0,
        min_speech_ms=250.0,
    )

    events = []
    for sequence, rms in enumerate([0.0, 0.02, 0.03, 0.0, 0.0]):
        events.extend(detector.process(_event(sequence, rms)))

    assert [event.type for event in events] == ["speech_start", "speech_end"]
    assert events[1].segment is not None
    assert events[1].segment.start_sequence == 1
    assert events[1].segment.end_sequence == 2
    assert events[1].segment.duration_ms == 400.0
    assert events[1].segment.mean_rms == 0.025


def test_rms_endpoint_detector_drops_short_blips() -> None:
    detector = RmsEndpointDetector(
        speech_rms_threshold=0.01,
        silence_ms=200.0,
        min_speech_ms=300.0,
    )

    events = []
    for sequence, rms in enumerate([0.02, 0.0]):
        events.extend(detector.process(_event(sequence, rms)))

    assert [event.type for event in events] == ["speech_start"]
    assert detector.flush("session-1") is None


def test_rms_vad_provider_preserves_rms_endpoint_behavior() -> None:
    provider = RmsVadProvider(
        RmsEndpointDetector(speech_rms_threshold=0.01, silence_ms=400.0, min_speech_ms=250.0)
    )

    events = []
    for sequence, rms in enumerate([0.0, 0.02, 0.03, 0.0, 0.0]):
        events.extend(provider.process(_event(sequence, rms)))

    assert provider.name == "rms"
    assert provider.latest_frame_stats is not None
    assert provider.latest_frame_stats.speech_probability is None
    assert [event.type for event in events] == ["speech_start", "speech_end"]


def test_create_vad_provider_defaults_to_rms() -> None:
    assert create_vad_provider("rms").name == "rms"
