from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from backend.audio.endpointing import EndpointEvent
from backend.audio.manager import AudioChunkEvent, now_ms
from backend.audio.vad import VadFrameStats, VadProvider, create_vad_provider

logger = logging.getLogger("proof.backend.audio.consumer")

EndpointHandler = Callable[[EndpointEvent], None | Awaitable[None]]


@dataclass(frozen=True)
class AudioConsumerStats:
    running: bool
    vad_provider: str
    consumed_chunks: int
    endpoint_events: int
    processing_errors: int
    vad_processing_errors: int
    last_consumed_at_ms: float | None
    last_error: str | None
    queue_depth: int
    recent_endpoint_events: int
    last_speech_probability: float | None


class EndpointingConsumer:
    """Drains the live audio queue and emits lightweight endpoint events."""

    def __init__(
        self,
        queue: asyncio.Queue[AudioChunkEvent],
        *,
        vad_provider: VadProvider | None = None,
        vad_provider_name: str = "rms",
        endpoint_handler: EndpointHandler | None = None,
        recent_event_limit: int = 100,
    ) -> None:
        self._queue = queue
        self._vad = vad_provider or create_vad_provider(vad_provider_name)
        self._endpoint_handler = endpoint_handler
        self._recent_events: deque[EndpointEvent] = deque(maxlen=recent_event_limit)
        self._task: asyncio.Task[None] | None = None
        self._consumed_chunks = 0
        self._endpoint_events = 0
        self._processing_errors = 0
        self._vad_processing_errors = 0
        self._last_consumed_at_ms: float | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self.run(), name="audio-endpointing-consumer")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                self._consume(event)
            except Exception as exc:  # noqa: BLE001 - keep the real-time consumer alive.
                self._processing_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "audio_consumer_error session_id=%s sequence=%s",
                    event.session_id,
                    event.packet.sequence,
                )
            finally:
                self._consumed_chunks += 1
                self._last_consumed_at_ms = now_ms()
                self._queue.task_done()

    def stats(self) -> AudioConsumerStats:
        return AudioConsumerStats(
            running=self.running,
            vad_provider=self._vad.name,
            consumed_chunks=self._consumed_chunks,
            endpoint_events=self._endpoint_events,
            processing_errors=self._processing_errors,
            vad_processing_errors=self._vad_processing_errors,
            last_consumed_at_ms=self._last_consumed_at_ms,
            last_error=self._last_error,
            queue_depth=self._queue.qsize(),
            recent_endpoint_events=len(self._recent_events),
            last_speech_probability=self.latest_frame_stats.speech_probability
            if self.latest_frame_stats is not None
            else None,
        )

    def recent_events(self) -> list[EndpointEvent]:
        return list(self._recent_events)

    @property
    def latest_frame_stats(self) -> VadFrameStats | None:
        return self._vad.latest_frame_stats

    def _consume(self, event: AudioChunkEvent) -> None:
        try:
            endpoint_events = self._vad.process(event)
        except Exception:
            self._vad_processing_errors += 1
            raise

        for endpoint_event in endpoint_events:
            self._endpoint_events += 1
            self._recent_events.append(endpoint_event)
            if self._endpoint_handler is not None:
                result = self._endpoint_handler(endpoint_event)
                if inspect.isawaitable(result):
                    asyncio.ensure_future(result)
