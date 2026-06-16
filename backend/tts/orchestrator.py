from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
import wave
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.audio.manager import now_ms
from backend.tts.playback import AudioPlayer
from backend.tts.providers import TtsProvider

logger = logging.getLogger("proof.backend.tts")


@dataclass(frozen=True)
class TtsJob:
    job_id: str
    text: str
    queued_at_ms: float


@dataclass(frozen=True)
class TtsSpeechResult:
    job_id: str
    text: str
    provider: str
    model_id: str
    voice_id: str
    voice_name: str
    queued_at_ms: float
    started_at_ms: float
    completed_at_ms: float
    ttfa_ms: float | None
    wall_time_s: float
    audio_bytes: int
    sample_rate: int
    dump_path: str | None = None
    error: str | None = None
    interrupted: bool = False
    interrupt_reason: str | None = None


@dataclass(frozen=True)
class TtsStats:
    enabled: bool
    running: bool
    provider: str
    model_id: str
    voice_id: str
    voice_name: str
    sample_rate: int
    player: str
    output_device: str | None
    playback_enabled: bool
    queued_jobs: int
    enqueued_jobs: int
    dropped_jobs: int
    completed_speeches: int
    processing_errors: int
    total_audio_bytes: int
    interrupted_speeches: int
    active_job_id: str | None
    dump_enabled: bool
    dump_dir: str | None
    last_started_at_ms: float | None
    last_completed_at_ms: float | None
    last_ttfa_ms: float | None
    last_error: str | None
    recent_speeches: int


class TtsOrchestrator:
    def __init__(
        self,
        *,
        enabled: bool,
        playback_enabled: bool,
        provider: TtsProvider,
        player: AudioPlayer,
        queue_max: int,
        dump_dir: Path | None = None,
        dump_enabled: bool = False,
        result_handler: Callable[[TtsSpeechResult], None] | None = None,
    ) -> None:
        self.enabled = enabled
        self.playback_enabled = playback_enabled
        self._provider = provider
        self._player = player
        self._queue: asyncio.Queue[TtsJob] = asyncio.Queue(maxsize=queue_max)
        self._dump_dir = dump_dir
        self._dump_enabled = dump_enabled
        self._task: asyncio.Task[None] | None = None
        self._recent_speeches: deque[TtsSpeechResult] = deque(maxlen=50)
        self._enqueued_jobs = 0
        self._dropped_jobs = 0
        self._completed_speeches = 0
        self._processing_errors = 0
        self._total_audio_bytes = 0
        self._interrupted_speeches = 0
        self._active_job_id: str | None = None
        self._interrupt_requested = threading.Event()
        self._interrupt_reason: str | None = None
        self._last_started_at_ms: float | None = None
        self._last_completed_at_ms: float | None = None
        self._last_ttfa_ms: float | None = None
        self._last_error: str | None = None
        self._result_handler = result_handler

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._task = asyncio.create_task(self.run(), name="tts-worker")

    async def stop(self) -> None:
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None
        self._player.close()

    async def run(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                result = await asyncio.to_thread(self._speak_sync, job)
                if result.error is not None:
                    self._processing_errors += 1
                    self._last_error = result.error
                elif result.interrupted:
                    self._interrupted_speeches += 1
                    self._last_error = None
                else:
                    self._completed_speeches += 1
                    self._last_error = None
                self._last_completed_at_ms = result.completed_at_ms
                self._last_ttfa_ms = result.ttfa_ms
                self._total_audio_bytes += result.audio_bytes
                self._recent_speeches.append(result)
                if self._result_handler is not None:
                    self._result_handler(result)
            except Exception as exc:  # noqa: BLE001 - keep live worker running.
                self._processing_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("tts_worker_error job_id=%s", job.job_id)
            finally:
                self._queue.task_done()

    def enqueue(self, text: str, *, interrupt: bool = False) -> TtsJob:
        if not self.enabled:
            raise RuntimeError(
                "TTS is disabled. Set PROOF_TTS_ENABLED=true to enable manual speech."
            )
        if not self.running:
            raise RuntimeError("TTS worker is not running")
        if interrupt:
            self.interrupt_current(reason="manual_interrupt")
        job = TtsJob(job_id=uuid.uuid4().hex[:16], text=text, queued_at_ms=now_ms())
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            _ = self._queue.get_nowait()
            self._queue.task_done()
            self._dropped_jobs += 1
            self._queue.put_nowait(job)
        self._enqueued_jobs += 1
        return job

    async def drain(self) -> None:
        await self._queue.join()

    def interrupt_current(self, reason: str = "interrupt") -> bool:
        self.clear_queue()
        if self._active_job_id is None:
            return False
        self._interrupt_reason = reason
        self._interrupt_requested.set()
        try:
            self._player.close()
        except Exception:  # noqa: BLE001 - interruption should not crash the backend.
            logger.exception("tts_player_interrupt_close_error")
        return True

    def clear_queue(self) -> None:
        while True:
            try:
                _ = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._queue.task_done()

    def stats(self) -> TtsStats:
        info = self._provider.info
        return TtsStats(
            enabled=self.enabled,
            running=self.running,
            provider=info.provider,
            model_id=info.model_id,
            voice_id=info.voice_id,
            voice_name=info.voice_name,
            sample_rate=info.sample_rate,
            player=self._player.name,
            output_device=self._player.output_device,
            playback_enabled=self.playback_enabled,
            queued_jobs=self._queue.qsize(),
            enqueued_jobs=self._enqueued_jobs,
            dropped_jobs=self._dropped_jobs,
            completed_speeches=self._completed_speeches,
            processing_errors=self._processing_errors,
            total_audio_bytes=self._total_audio_bytes,
            interrupted_speeches=self._interrupted_speeches,
            active_job_id=self._active_job_id,
            dump_enabled=self._dump_enabled,
            dump_dir=str(self._dump_dir) if self._dump_dir is not None else None,
            last_started_at_ms=self._last_started_at_ms,
            last_completed_at_ms=self._last_completed_at_ms,
            last_ttfa_ms=self._last_ttfa_ms,
            last_error=self._last_error,
            recent_speeches=len(self._recent_speeches),
        )

    def recent_speeches(self) -> list[TtsSpeechResult]:
        return list(self._recent_speeches)

    def _speak_sync(self, job: TtsJob) -> TtsSpeechResult:
        info = self._provider.info
        self._active_job_id = job.job_id
        self._interrupt_requested.clear()
        self._interrupt_reason = None
        started_at_ms = now_ms()
        self._last_started_at_ms = started_at_ms
        started = time.perf_counter()
        first_audio_at = None
        audio_bytes = 0
        error = None
        interrupted = False
        interrupt_reason = None
        dump_file = _TtsWavDump(
            dump_dir=self._dump_dir,
            enabled=self._dump_enabled,
            job_id=job.job_id,
            sample_rate=info.sample_rate,
        )
        try:
            for chunk in self._provider.stream_speech(job.text):
                if self._interrupt_requested.is_set():
                    interrupted = True
                    interrupt_reason = self._interrupt_reason
                    break
                if not chunk:
                    continue
                if first_audio_at is None:
                    first_audio_at = time.perf_counter()
                dump_file.write(chunk)
                self._player.write_pcm16(chunk, sample_rate=info.sample_rate)
                audio_bytes += len(chunk)
                if self._interrupt_requested.is_set():
                    interrupted = True
                    interrupt_reason = self._interrupt_reason
                    break
        except Exception as exc:  # noqa: BLE001 - convert provider/player failures into stats.
            if self._interrupt_requested.is_set():
                interrupted = True
                interrupt_reason = self._interrupt_reason
            else:
                error = f"{type(exc).__name__}: {exc}"
        finally:
            dump_path = dump_file.close()
        completed = time.perf_counter()
        completed_at_ms = now_ms()
        ttfa_ms = (first_audio_at - started) * 1000.0 if first_audio_at is not None else None
        try:
            return TtsSpeechResult(
                job_id=job.job_id,
                text=job.text,
                provider=info.provider,
                model_id=info.model_id,
                voice_id=info.voice_id,
                voice_name=info.voice_name,
                queued_at_ms=job.queued_at_ms,
                started_at_ms=started_at_ms,
                completed_at_ms=completed_at_ms,
                ttfa_ms=ttfa_ms,
                wall_time_s=completed - started,
                audio_bytes=audio_bytes,
                sample_rate=info.sample_rate,
                dump_path=dump_path,
                error=error,
                interrupted=interrupted,
                interrupt_reason=interrupt_reason,
            )
        finally:
            self._active_job_id = None
            self._interrupt_requested.clear()
            self._interrupt_reason = None


class _TtsWavDump:
    def __init__(
        self,
        *,
        dump_dir: Path | None,
        enabled: bool,
        job_id: str,
        sample_rate: int,
    ) -> None:
        self._path: Path | None = None
        self._wav: wave.Wave_write | None = None
        if not enabled or dump_dir is None:
            return
        dump_dir.mkdir(parents=True, exist_ok=True)
        self._path = dump_dir / f"{job_id}.wav"
        self._wav = wave.open(str(self._path), "wb")  # noqa: SIM115 - closed by close().
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    def write(self, pcm16: bytes) -> None:
        if self._wav is not None:
            self._wav.writeframes(pcm16)

    def close(self) -> str | None:
        if self._wav is not None:
            self._wav.close()
            self._wav = None
        return str(self._path) if self._path is not None else None
