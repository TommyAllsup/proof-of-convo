from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from backend.audio.endpointing import EndpointEvent, SpeechSegment
from backend.audio.frames import AudioPacket
from backend.audio.live_stt import AudioWindowBuffer, LiveSttOrchestrator
from backend.audio.manager import AudioChunkEvent


@pytest.mark.asyncio
async def test_live_stt_orchestrator_transcribes_endpoint_job() -> None:
    orchestrator = LiveSttOrchestrator(
        enabled=True,
        provider_name="fake",
        model_id=None,
        language=None,
        vad_provider_name="rms",
        queue_max=4,
        buffer_history_ms=5_000,
        pre_roll_ms=100,
        post_roll_ms=100,
        diarization_provider_name="single_speaker",
    )
    orchestrator.set_speaker_label(session_id="session-1", speaker="Speaker_1", label="Avery")
    orchestrator.start()

    for sequence in range(5):
        orchestrator.observe_chunk(_event(sequence))

    segment = SpeechSegment(
        session_id="session-1",
        start_ms=200.0,
        end_ms=600.0,
        duration_ms=400.0,
        start_sequence=1,
        end_sequence=2,
        peak=0.5,
        mean_rms=0.2,
    )
    orchestrator.handle_endpoint(
        EndpointEvent(
            type="speech_end",
            session_id="session-1",
            segment=segment,
            sequence=4,
            event_ms=1_000.0,
        )
    )

    for _ in range(20):
        if orchestrator.stats().completed_transcripts:
            break
        await asyncio.sleep(0.01)
    await orchestrator.stop()

    stats = orchestrator.stats()
    assert stats.enqueued_jobs == 1
    assert stats.completed_transcripts == 1
    assert stats.processing_errors == 0
    assert stats.diarization_provider == "single_speaker"
    recent = orchestrator.recent_transcripts()
    assert len(recent) == 1
    assert recent[0].window.vad_provider == "rms"
    assert recent[0].window.padded_start_ms == 100.0
    assert recent[0].window.padded_end_ms == 700.0
    assert recent[0].transcript.provider == "fake"
    assert recent[0].speaker.speaker == "Speaker_1"
    assert recent[0].speaker.speaker_label == "Avery"
    assert recent[0].speaker.provider == "single_speaker"
    assert recent[0].speaker.merge_state == "fixed"
    assert recent[0].utterance.speaker == "Speaker_1"
    assert recent[0].utterance.speaker_label == "Avery"
    assert recent[0].utterance.diarization_provider == "single_speaker"
    assert recent[0].utterance.speaker_merge_state == "fixed"
    assert recent[0].utterance.text.startswith("[fake transcript")
    assert recent[0].utterance.is_final is True

    orchestrator.set_speaker_label(session_id="session-1", speaker="Speaker_1", label="Morgan")
    labeled = orchestrator.recent_transcripts()
    assert labeled[0].speaker.speaker_label == "Morgan"
    assert labeled[0].utterance.speaker_label == "Morgan"


def test_audio_window_buffer_aligns_capture_clock_segments_to_chunk_clock() -> None:
    buffer = AudioWindowBuffer(max_history_ms=5_000)
    for sequence in range(5):
        buffer.add(
            _event(
                sequence,
                capture_started_at_ms=0.0,
                first_chunk_started_at_ms=1_000.0,
            )
        )

    segment = SpeechSegment(
        session_id="session-1",
        start_ms=200.0,
        end_ms=600.0,
        duration_ms=400.0,
        start_sequence=1,
        end_sequence=2,
        peak=0.5,
        mean_rms=0.2,
    )

    job = buffer.create_job(
        segment,
        vad_provider="silero_onnx",
        pre_roll_ms=100.0,
        post_roll_ms=100.0,
    )

    assert job is not None
    assert job.window.start_ms == 1_200.0
    assert job.window.end_ms == 1_600.0
    assert job.window.padded_start_ms == 1_100.0
    assert job.window.padded_end_ms == 1_700.0
    assert len(job.pcm16) == 19_200


def _event(
    sequence: int,
    *,
    capture_started_at_ms: float = 0.0,
    first_chunk_started_at_ms: float = 0.0,
) -> AudioChunkEvent:
    sample_rate = 16_000
    sample_count = 3_200
    chunk_started_at_ms = first_chunk_started_at_ms + sequence * 200.0
    index = np.arange(sequence * sample_count, (sequence + 1) * sample_count)
    wave_data = 0.35 * np.sin(2.0 * math.pi * 440.0 * index / sample_rate)
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
        peak=0.5,
        received_at_ms=chunk_started_at_ms,
    )
