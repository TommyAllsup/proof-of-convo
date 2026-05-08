from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from backend.audio.diarization import HeuristicSpeakerDiarizer, SpeakerAttribution
from backend.audio.endpointing import EndpointEvent, SpeechSegment
from backend.audio.frames import pcm16_to_float32
from backend.audio.manager import AudioChunkEvent, now_ms
from backend.audio.stt import SttProvider, SttTranscript, create_stt_provider
from backend.audio.stt_windows import UtteranceWindow
from backend.models.audio import Utterance

logger = logging.getLogger("proof.backend.audio.live_stt")


@dataclass(frozen=True)
class LiveSttJob:
    window: UtteranceWindow
    pcm16: bytes


@dataclass(frozen=True)
class LiveTranscript:
    window: UtteranceWindow
    transcript: SttTranscript
    speaker: SpeakerAttribution
    utterance: Utterance
    completed_at_ms: float


@dataclass(frozen=True)
class LiveSttStats:
    enabled: bool
    running: bool
    provider: str
    model_id: str
    model_load_time_s: float | None
    queued_jobs: int
    enqueued_jobs: int
    dropped_jobs: int
    completed_transcripts: int
    processing_errors: int
    last_completed_at_ms: float | None
    last_error: str | None
    recent_transcripts: int


@dataclass(frozen=True)
class _BufferedChunk:
    session_id: str
    sequence: int
    start_ms: float
    end_ms: float
    stream_start_ms: float
    stream_end_ms: float
    sample_rate: int
    pcm16: bytes
    rms: float
    peak: float


class AudioWindowBuffer:
    def __init__(self, *, max_history_ms: float = 120_000.0) -> None:
        self._max_history_ms = max_history_ms
        self._chunks: dict[str, deque[_BufferedChunk]] = {}
        self._stream_sample_offsets: dict[str, int] = {}

    def add(self, event: AudioChunkEvent) -> None:
        stream_sample_offset = self._stream_sample_offsets.get(event.session_id, 0)
        stream_start_ms = event.packet.capture_started_at_ms + (
            stream_sample_offset * 1000.0 / event.packet.sample_rate
        )
        stream_end_ms = stream_start_ms + event.packet.duration_ms
        self._stream_sample_offsets[event.session_id] = (
            stream_sample_offset + event.packet.sample_count
        )
        chunk = _BufferedChunk(
            session_id=event.session_id,
            sequence=event.packet.sequence,
            start_ms=event.packet.chunk_started_at_ms,
            end_ms=event.packet.chunk_started_at_ms + event.packet.duration_ms,
            stream_start_ms=stream_start_ms,
            stream_end_ms=stream_end_ms,
            sample_rate=event.packet.sample_rate,
            pcm16=event.packet.pcm16,
            rms=event.rms,
            peak=event.peak,
        )
        chunks = self._chunks.setdefault(event.session_id, deque())
        chunks.append(chunk)
        cutoff_ms = chunk.end_ms - self._max_history_ms
        while chunks and chunks[0].end_ms < cutoff_ms:
            chunks.popleft()

    def create_job(
        self,
        segment: SpeechSegment,
        *,
        vad_provider: str,
        pre_roll_ms: float,
        post_roll_ms: float,
    ) -> LiveSttJob | None:
        chunks = self._chunks.get(segment.session_id)
        if not chunks:
            return None

        sample_rate = chunks[-1].sample_rate
        clock = _select_segment_clock(chunks, segment)
        buffer_start_ms = _clock_start_ms(chunks[0], clock)
        buffer_end_ms = _clock_end_ms(chunks[-1], clock)
        padded_start_ms = max(buffer_start_ms, segment.start_ms - pre_roll_ms)
        padded_end_ms = min(buffer_end_ms, segment.end_ms + post_roll_ms)
        pcm_parts: list[bytes] = []
        peak = segment.peak
        rms_sum = 0.0
        rms_count = 0
        for chunk in chunks:
            chunk_start_ms = _clock_start_ms(chunk, clock)
            chunk_end_ms = _clock_end_ms(chunk, clock)
            if chunk_end_ms <= padded_start_ms or chunk_start_ms >= padded_end_ms:
                continue
            if chunk.sample_rate != sample_rate:
                raise ValueError("mixed sample rates in live STT buffer")
            start_sample = _ms_offset_to_sample(
                max(padded_start_ms, chunk_start_ms) - chunk_start_ms,
                sample_rate,
                floor=True,
            )
            end_sample = _ms_offset_to_sample(
                min(padded_end_ms, chunk_end_ms) - chunk_start_ms,
                sample_rate,
                floor=False,
            )
            if end_sample <= start_sample:
                continue
            pcm_parts.append(chunk.pcm16[start_sample * 2 : end_sample * 2])
            peak = max(peak, chunk.peak)
            rms_sum += chunk.rms
            rms_count += 1

        pcm16 = b"".join(pcm_parts)
        if not pcm16:
            return None

        aligned_start_ms = _clock_to_chunk_ms(chunks, segment.start_ms, clock)
        aligned_end_ms = _clock_to_chunk_ms(chunks, segment.end_ms, clock)
        aligned_padded_start_ms = _clock_to_chunk_ms(chunks, padded_start_ms, clock)
        aligned_padded_end_ms = _clock_to_chunk_ms(chunks, padded_end_ms, clock)
        window = UtteranceWindow(
            window_id=_live_window_id(
                session_id=segment.session_id,
                vad_provider=vad_provider,
                start_ms=aligned_start_ms,
                end_ms=aligned_end_ms,
            ),
            session_id=segment.session_id,
            source_wav=f"live://{segment.session_id}",
            sample_rate=sample_rate,
            vad_provider=vad_provider,
            start_ms=aligned_start_ms,
            end_ms=aligned_end_ms,
            duration_ms=max(0.0, aligned_end_ms - aligned_start_ms),
            padded_start_ms=aligned_padded_start_ms,
            padded_end_ms=aligned_padded_end_ms,
            padded_duration_ms=max(0.0, aligned_padded_end_ms - aligned_padded_start_ms),
            start_sequence=segment.start_sequence,
            end_sequence=segment.end_sequence,
            peak=peak,
            mean_rms=rms_sum / rms_count if rms_count else segment.mean_rms,
        )
        return LiveSttJob(window=window, pcm16=pcm16)

    def clear_session(self, session_id: str) -> None:
        self._chunks.pop(session_id, None)
        self._stream_sample_offsets.pop(session_id, None)


class LiveSttOrchestrator:
    def __init__(
        self,
        *,
        enabled: bool,
        provider_name: str,
        model_id: str | None,
        language: str | None,
        vad_provider_name: str,
        queue_max: int,
        buffer_history_ms: float,
        pre_roll_ms: float,
        post_roll_ms: float,
        provider: SttProvider | None = None,
    ) -> None:
        self.enabled = enabled
        self._provider = provider or create_stt_provider(
            provider_name,
            model_id=model_id,
            language=language,
        )
        self._vad_provider_name = vad_provider_name
        self._queue: asyncio.Queue[LiveSttJob] = asyncio.Queue(maxsize=queue_max)
        self._buffer = AudioWindowBuffer(max_history_ms=buffer_history_ms)
        self._diarizer = HeuristicSpeakerDiarizer()
        self._pre_roll_ms = pre_roll_ms
        self._post_roll_ms = post_roll_ms
        self._task: asyncio.Task[None] | None = None
        self._worker_thread_prepared = False
        self._recent_transcripts: deque[LiveTranscript] = deque(maxlen=100)
        self._model_load_time_s: float | None = None
        self._enqueued_jobs = 0
        self._dropped_jobs = 0
        self._completed_transcripts = 0
        self._processing_errors = 0
        self._last_completed_at_ms: float | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._task = asyncio.create_task(self.run(), name="live-stt-worker")

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
            job = await self._queue.get()
            try:
                transcript, audio = await asyncio.to_thread(self._transcribe_job_sync, job)
                speaker = self._diarizer.assign(window=job.window, audio=audio)
                utterance = _utterance_from_transcript(job.window, transcript, speaker)
                if transcript.error is not None:
                    self._processing_errors += 1
                    self._last_error = transcript.error
                self._completed_transcripts += 1
                self._last_completed_at_ms = now_ms()
                self._recent_transcripts.append(
                    LiveTranscript(
                        window=job.window,
                        transcript=transcript,
                        speaker=speaker,
                        utterance=utterance,
                        completed_at_ms=self._last_completed_at_ms,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep live worker running.
                self._processing_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("live_stt_worker_error window_id=%s", job.window.window_id)
            finally:
                self._queue.task_done()

    def observe_chunk(self, event: AudioChunkEvent) -> None:
        if self.enabled:
            self._buffer.add(event)

    def handle_endpoint(self, event: EndpointEvent) -> None:
        if not self.enabled or event.segment is None:
            return
        job = self._buffer.create_job(
            event.segment,
            vad_provider=self._vad_provider_name,
            pre_roll_ms=self._pre_roll_ms,
            post_roll_ms=self._post_roll_ms,
        )
        if job is None:
            self._processing_errors += 1
            self._last_error = "missing buffered audio for endpoint"
            return
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            _ = self._queue.get_nowait()
            self._queue.task_done()
            self._dropped_jobs += 1
            self._queue.put_nowait(job)
        self._enqueued_jobs += 1

    def stats(self) -> LiveSttStats:
        return LiveSttStats(
            enabled=self.enabled,
            running=self.running,
            provider=self._provider.name,
            model_id=self._provider.model_info.model_id,
            model_load_time_s=self._model_load_time_s,
            queued_jobs=self._queue.qsize(),
            enqueued_jobs=self._enqueued_jobs,
            dropped_jobs=self._dropped_jobs,
            completed_transcripts=self._completed_transcripts,
            processing_errors=self._processing_errors,
            last_completed_at_ms=self._last_completed_at_ms,
            last_error=self._last_error,
            recent_transcripts=len(self._recent_transcripts),
        )

    def recent_transcripts(self) -> list[LiveTranscript]:
        return list(self._recent_transcripts)

    def _transcribe_job_sync(self, job: LiveSttJob) -> tuple[SttTranscript, Any]:
        if not self._worker_thread_prepared:
            self._model_load_time_s = self._provider.prepare()
            self._worker_thread_prepared = True
        audio = pcm16_to_float32(job.pcm16)
        return self._provider.transcribe_audio(job.window, audio), audio


def _ms_offset_to_sample(offset_ms: float, sample_rate: int, *, floor: bool) -> int:
    sample = offset_ms * sample_rate / 1000.0
    return max(0, int(math.floor(sample) if floor else math.ceil(sample)))


def _select_segment_clock(chunks: deque[_BufferedChunk], segment: SpeechSegment) -> str:
    chunk_overlap_ms = _total_overlap_ms(
        chunks,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        clock="chunk",
    )
    stream_overlap_ms = _total_overlap_ms(
        chunks,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        clock="stream",
    )
    return "stream" if stream_overlap_ms > chunk_overlap_ms else "chunk"


def _total_overlap_ms(
    chunks: deque[_BufferedChunk],
    *,
    start_ms: float,
    end_ms: float,
    clock: str,
) -> float:
    total = 0.0
    for chunk in chunks:
        overlap_start_ms = max(start_ms, _clock_start_ms(chunk, clock))
        overlap_end_ms = min(end_ms, _clock_end_ms(chunk, clock))
        total += max(0.0, overlap_end_ms - overlap_start_ms)
    return total


def _clock_start_ms(chunk: _BufferedChunk, clock: str) -> float:
    return chunk.stream_start_ms if clock == "stream" else chunk.start_ms


def _clock_end_ms(chunk: _BufferedChunk, clock: str) -> float:
    return chunk.stream_end_ms if clock == "stream" else chunk.end_ms


def _clock_to_chunk_ms(chunks: deque[_BufferedChunk], timestamp_ms: float, clock: str) -> float:
    if clock == "chunk":
        return timestamp_ms

    for chunk in chunks:
        stream_start_ms = chunk.stream_start_ms
        stream_end_ms = chunk.stream_end_ms
        if stream_start_ms <= timestamp_ms <= stream_end_ms:
            return chunk.start_ms + (timestamp_ms - stream_start_ms)

    first = chunks[0]
    if timestamp_ms < first.stream_start_ms:
        return first.start_ms + (timestamp_ms - first.stream_start_ms)

    last = chunks[-1]
    return last.end_ms + (timestamp_ms - last.stream_end_ms)


def _live_window_id(
    *,
    session_id: str,
    vad_provider: str,
    start_ms: float,
    end_ms: float,
) -> str:
    material = f"live|{session_id}|{vad_provider}|{start_ms:.3f}|{end_ms:.3f}"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _utterance_from_transcript(
    window: UtteranceWindow,
    transcript: SttTranscript,
    speaker: SpeakerAttribution,
) -> Utterance:
    return Utterance(
        utterance_id=window.window_id,
        session_id=window.session_id,
        speaker=speaker.speaker,
        start_ts=window.start_ms / 1000.0,
        end_ts=window.end_ms / 1000.0,
        start_ms=window.start_ms,
        end_ms=window.end_ms,
        text=transcript.text,
        is_final=True,
        confidence=transcript.confidence,
        speaker_confidence=speaker.confidence,
        stt_provider=transcript.provider,
        stt_model=transcript.model_id,
        vad_provider=window.vad_provider,
        raw_audio_ref=window.source_wav,
    )
