from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from backend.audio.frames import AudioPacket, audio_levels, pcm16_to_float32
from backend.audio.wav_dump import WavDumpWriter
from backend.models.audio import ChunkAck, SessionStart, SessionStats


def now_ms() -> float:
    return time.time() * 1000.0


@dataclass
class AudioChunkEvent:
    session_id: str
    packet: AudioPacket
    rms: float
    peak: float
    received_at_ms: float


class AudioSession:
    def __init__(self, start: SessionStart, dump_dir: Path, dump_seconds: int) -> None:
        started_at_ms = start.client_started_at_ms or now_ms()
        self.stats = SessionStats(
            session_id=start.session_id,
            tab_id=start.tab_id,
            meeting_url=start.meeting_url,
            sample_rate=start.sample_rate,
            started_at_ms=started_at_ms,
        )
        self.dump_writer: WavDumpWriter | None = None
        if dump_seconds > 0:
            safe_session = "".join(
                char if char.isalnum() or char in {"-", "_"} else "_" for char in start.session_id
            )
            dump_path = dump_dir / f"{safe_session}_first_{dump_seconds}s.wav"
            self.dump_writer = WavDumpWriter(dump_path, start.sample_rate, dump_seconds)
            self.stats.dump_path = str(dump_path)

    def ingest(self, packet: AudioPacket, received_at_ms: float) -> tuple[float, float]:
        samples = pcm16_to_float32(packet.pcm16)
        rms, peak = audio_levels(samples)

        if self.stats.last_sequence is not None:
            gap = packet.sequence - self.stats.last_sequence - 1
            if gap > 0:
                self.stats.dropped_chunks += gap

        self.stats.total_chunks += 1
        self.stats.total_samples += packet.sample_count
        self.stats.total_bytes += len(packet.pcm16)
        self.stats.last_sequence = packet.sequence
        self.stats.last_packet_at_ms = received_at_ms
        self.stats.last_latency_ms = (
            received_at_ms - packet.client_sent_at_ms if packet.client_sent_at_ms else None
        )
        self.stats.last_rms = rms
        self.stats.last_peak = peak

        if self.dump_writer is not None and packet.sample_rate == self.stats.sample_rate:
            self.dump_writer.write(packet.pcm16)

        return rms, peak

    def close(self) -> None:
        if self.dump_writer is not None:
            self.dump_writer.close()


class AudioStreamManager:
    def __init__(self, *, queue_max: int, dump_dir: Path, dump_seconds: int) -> None:
        self._queue: asyncio.Queue[AudioChunkEvent] = asyncio.Queue(maxsize=queue_max)
        self._sessions: dict[str, AudioSession] = {}
        self._dump_dir = dump_dir
        self._dump_seconds = dump_seconds

    @property
    def queue(self) -> asyncio.Queue[AudioChunkEvent]:
        return self._queue

    def start_session(self, start: SessionStart) -> SessionStats:
        existing = self._sessions.pop(start.session_id, None)
        if existing is not None:
            existing.close()

        session = AudioSession(start, self._dump_dir, self._dump_seconds)
        self._sessions[start.session_id] = session
        return session.stats

    async def ingest_packet(
        self, *, session_id: str, packet: AudioPacket, received_at_ms: float
    ) -> ChunkAck:
        session = self._sessions.get(session_id)
        if session is None:
            start = SessionStart(
                type="session_start",
                session_id=session_id,
                tab_id=packet.tab_id,
                sample_rate=packet.sample_rate,
                client_started_at_ms=packet.capture_started_at_ms,
            )
            self.start_session(start)
            session = self._sessions[session_id]

        rms, peak = session.ingest(packet, received_at_ms)
        event = AudioChunkEvent(
            session_id=session_id,
            packet=packet,
            rms=rms,
            peak=peak,
            received_at_ms=received_at_ms,
        )
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Phase 2 may not be attached yet. Keep capture live and reserve dropped_chunks for
            # real wire-level sequence gaps, not stale downstream events.
            _ = self._queue.get_nowait()
            self._queue.put_nowait(event)

        return ChunkAck(
            session_id=session_id,
            sequence=packet.sequence,
            received_at_ms=received_at_ms,
            latency_ms=session.stats.last_latency_ms,
            rms=rms,
            peak=peak,
            total_chunks=session.stats.total_chunks,
            dropped_chunks=session.stats.dropped_chunks,
            queued_chunks=self._queue.qsize(),
        )

    def stop_session(self, session_id: str) -> SessionStats | None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return None
        session.close()
        return session.stats

    def get_session(self, session_id: str) -> SessionStats | None:
        session = self._sessions.get(session_id)
        return session.stats if session is not None else None

    def list_sessions(self) -> list[SessionStats]:
        return [session.stats for session in self._sessions.values()]

    def close_all(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
