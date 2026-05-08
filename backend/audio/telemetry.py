from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

from backend.audio.frames import AudioPacket
from backend.models.audio import SessionStart, SessionStats


class TelemetryWriter:
    """Persists per-session capture metadata and chunk-level health metrics."""

    def __init__(self, session_id: str, telemetry_dir: Path) -> None:
        self.session_id = session_id
        safe_session = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_" for char in session_id
        )
        self.session_path = telemetry_dir / f"{safe_session}_session.json"
        self.chunks_path = telemetry_dir / f"{safe_session}_chunks.jsonl"
        self._chunks_file: TextIO | None = None

    def start(self, start: SessionStart, stats: SessionStats) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_session(
            {
                "type": "session_started",
                "session": _session_start_payload(start),
                "stats": stats.model_dump(mode="json"),
            }
        )

    def write_chunk(
        self,
        *,
        packet: AudioPacket,
        received_at_ms: float,
        rms: float,
        peak: float,
        latency_ms: float | None,
        total_chunks: int,
        dropped_chunks: int,
        queued_chunks: int,
    ) -> None:
        if self._chunks_file is None:
            self.chunks_path.parent.mkdir(parents=True, exist_ok=True)
            self._chunks_file = self.chunks_path.open("a", encoding="utf-8")

        payload = {
            "type": "audio_chunk",
            "session_id": self.session_id,
            "sequence": packet.sequence,
            "tab_id": packet.tab_id,
            "sample_rate": packet.sample_rate,
            "sample_count": packet.sample_count,
            "chunk_started_at_ms": packet.chunk_started_at_ms,
            "client_sent_at_ms": packet.client_sent_at_ms,
            "received_at_ms": received_at_ms,
            "latency_ms": latency_ms,
            "rms": rms,
            "peak": peak,
            "total_chunks": total_chunks,
            "dropped_chunks": dropped_chunks,
            "queued_chunks": queued_chunks,
        }
        self._chunks_file.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._chunks_file.flush()

    def stop(self, stats: SessionStats, *, stopped_at_ms: float, reason: str | None) -> None:
        self._write_session(
            {
                "type": "session_stopped",
                "stopped_at_ms": stopped_at_ms,
                "reason": reason,
                "stats": stats.model_dump(mode="json"),
                "artifacts": {
                    "chunks_jsonl": str(self.chunks_path),
                    "session_json": str(self.session_path),
                },
            }
        )
        self.close()

    def close(self) -> None:
        if self._chunks_file is not None:
            self._chunks_file.close()
            self._chunks_file = None

    def _write_session(self, payload: dict[str, Any]) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _session_start_payload(start: SessionStart) -> dict[str, Any]:
    return {
        "session_id": start.session_id,
        "tab_id": start.tab_id,
        "meeting_url": start.meeting_url,
        "sample_rate": start.sample_rate,
        "chunk_ms": start.chunk_ms,
        "client_started_at_ms": start.client_started_at_ms,
        "client_sent_at_ms": start.client_sent_at_ms,
        "telemetry_enabled": start.telemetry_enabled,
    }
