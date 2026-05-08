from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionStart(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["session_start"]
    session_id: str = Field(min_length=1)
    tab_id: int | None = None
    meeting_url: str | None = None
    sample_rate: int = 16_000
    chunk_ms: int = 200
    client_started_at_ms: float | None = None
    client_sent_at_ms: float | None = None
    telemetry_enabled: bool = True


class SessionStop(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["session_stop"]
    session_id: str
    reason: str = "client_stop"
    client_sent_at_ms: float | None = None


class ClientPing(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["ping"]
    session_id: str | None = None
    client_sent_at_ms: float | None = None


class SessionStats(BaseModel):
    session_id: str
    tab_id: int | None = None
    meeting_url: str | None = None
    sample_rate: int
    started_at_ms: float
    last_packet_at_ms: float | None = None
    total_chunks: int = 0
    total_samples: int = 0
    total_bytes: int = 0
    dropped_chunks: int = 0
    last_sequence: int | None = None
    last_latency_ms: float | None = None
    last_rms: float = 0.0
    last_peak: float = 0.0
    dump_path: str | None = None
    telemetry_session_path: str | None = None
    telemetry_chunks_path: str | None = None


class ChunkAck(BaseModel):
    type: Literal["chunk_ack"] = "chunk_ack"
    session_id: str
    sequence: int
    received_at_ms: float
    latency_ms: float | None
    rms: float
    peak: float
    total_chunks: int
    dropped_chunks: int
    queued_chunks: int


class SessionAck(BaseModel):
    type: Literal["session_ack"] = "session_ack"
    session_id: str
    received_at_ms: float
    sample_rate: int
    dump_path: str | None = None
    telemetry_session_path: str | None = None
    telemetry_chunks_path: str | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    received_at_ms: float


class Utterance(BaseModel):
    type: Literal["utterance"] = "utterance"
    utterance_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    speaker: str = Field(min_length=1)
    start_ts: float
    end_ts: float
    start_ms: float
    end_ms: float
    text: str
    is_final: bool = True
    confidence: float | None = None
    speaker_confidence: float | None = None
    stt_provider: str
    stt_model: str
    vad_provider: str
    raw_audio_ref: str | None = None
