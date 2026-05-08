from __future__ import annotations

import asyncio

import pytest

from backend.audio.consumer import EndpointingConsumer
from backend.audio.frames import AudioPacket
from backend.audio.manager import AudioChunkEvent


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


@pytest.mark.asyncio
async def test_endpointing_consumer_drains_queue_and_emits_events() -> None:
    queue: asyncio.Queue[AudioChunkEvent] = asyncio.Queue()
    consumer = EndpointingConsumer(queue)
    consumer.start()

    for sequence, rms in enumerate([0.0, 0.02, 0.03, 0.0, 0.0, 0.0]):
        await queue.put(_event(sequence, rms))

    await asyncio.wait_for(queue.join(), timeout=1.0)
    await consumer.stop()

    stats = consumer.stats()
    assert stats.running is False
    assert stats.consumed_chunks == 6
    assert stats.endpoint_events == 2
    assert stats.processing_errors == 0
    assert stats.queue_depth == 0
    assert [event.type for event in consumer.recent_events()] == ["speech_start", "speech_end"]


@pytest.mark.asyncio
async def test_endpointing_consumer_stop_cancels_cleanly() -> None:
    queue: asyncio.Queue[AudioChunkEvent] = asyncio.Queue()
    consumer = EndpointingConsumer(queue)
    consumer.start()

    assert consumer.stats().running is True

    await consumer.stop()

    assert consumer.stats().running is False


@pytest.mark.asyncio
async def test_endpointing_consumer_recovers_from_handler_error() -> None:
    queue: asyncio.Queue[AudioChunkEvent] = asyncio.Queue()

    def failing_handler(_: object) -> None:
        raise RuntimeError("handler failed")

    consumer = EndpointingConsumer(queue, endpoint_handler=failing_handler)
    consumer.start()

    for sequence, rms in enumerate([0.02, 0.0, 0.0, 0.0, 0.02]):
        await queue.put(_event(sequence, rms))

    await asyncio.wait_for(queue.join(), timeout=1.0)
    await consumer.stop()

    stats = consumer.stats()
    assert stats.consumed_chunks == 5
    assert stats.endpoint_events >= 1
    assert stats.processing_errors == 2
    assert stats.last_error == "RuntimeError: handler failed"
    assert stats.queue_depth == 0
