from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.audio.manager import AudioChunkEvent


@dataclass(frozen=True)
class SpeechSegment:
    session_id: str
    start_ms: float
    end_ms: float
    duration_ms: float
    start_sequence: int
    end_sequence: int
    peak: float
    mean_rms: float


@dataclass(frozen=True)
class EndpointEvent:
    type: Literal["speech_start", "speech_end"]
    session_id: str
    segment: SpeechSegment | None
    sequence: int
    event_ms: float


@dataclass
class _OpenSegment:
    session_id: str
    start_ms: float
    start_sequence: int
    last_voice_ms: float
    last_sequence: int
    peak: float
    rms_sum: float
    rms_count: int


class RmsEndpointDetector:
    """Simple streaming endpoint detector used as the Phase 2 baseline.

    This is intentionally model-free. It gives us deterministic endpointing over
    the existing PCM stream while we benchmark Silero/MLX VAD.
    """

    def __init__(
        self,
        *,
        speech_rms_threshold: float = 0.012,
        silence_ms: float = 500.0,
        min_speech_ms: float = 250.0,
    ) -> None:
        if speech_rms_threshold <= 0:
            raise ValueError("speech_rms_threshold must be positive")
        if silence_ms <= 0:
            raise ValueError("silence_ms must be positive")
        if min_speech_ms < 0:
            raise ValueError("min_speech_ms must be non-negative")

        self.speech_rms_threshold = speech_rms_threshold
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self._open: dict[str, _OpenSegment] = {}

    def process(self, event: AudioChunkEvent) -> list[EndpointEvent]:
        chunk_start_ms = event.packet.chunk_started_at_ms
        chunk_end_ms = chunk_start_ms + event.packet.duration_ms
        is_voice = event.rms >= self.speech_rms_threshold
        open_segment = self._open.get(event.session_id)
        emitted: list[EndpointEvent] = []

        if is_voice:
            if open_segment is None:
                self._open[event.session_id] = _OpenSegment(
                    session_id=event.session_id,
                    start_ms=chunk_start_ms,
                    start_sequence=event.packet.sequence,
                    last_voice_ms=chunk_end_ms,
                    last_sequence=event.packet.sequence,
                    peak=event.peak,
                    rms_sum=event.rms,
                    rms_count=1,
                )
                emitted.append(
                    EndpointEvent(
                        type="speech_start",
                        session_id=event.session_id,
                        segment=None,
                        sequence=event.packet.sequence,
                        event_ms=chunk_start_ms,
                    )
                )
            else:
                open_segment.last_voice_ms = chunk_end_ms
                open_segment.last_sequence = event.packet.sequence
                open_segment.peak = max(open_segment.peak, event.peak)
                open_segment.rms_sum += event.rms
                open_segment.rms_count += 1

            return emitted

        if open_segment is None:
            return emitted

        silent_for_ms = chunk_end_ms - open_segment.last_voice_ms
        if silent_for_ms >= self.silence_ms:
            segment = self._close(event.session_id)
            if segment is not None:
                emitted.append(
                    EndpointEvent(
                        type="speech_end",
                        session_id=event.session_id,
                        segment=segment,
                        sequence=event.packet.sequence,
                        event_ms=chunk_end_ms,
                    )
                )

        return emitted

    def flush(self, session_id: str) -> SpeechSegment | None:
        return self._close(session_id)

    def _close(self, session_id: str) -> SpeechSegment | None:
        open_segment = self._open.pop(session_id, None)
        if open_segment is None:
            return None

        duration_ms = open_segment.last_voice_ms - open_segment.start_ms
        if duration_ms < self.min_speech_ms:
            return None

        return SpeechSegment(
            session_id=open_segment.session_id,
            start_ms=open_segment.start_ms,
            end_ms=open_segment.last_voice_ms,
            duration_ms=duration_ms,
            start_sequence=open_segment.start_sequence,
            end_sequence=open_segment.last_sequence,
            peak=open_segment.peak,
            mean_rms=open_segment.rms_sum / open_segment.rms_count,
        )
