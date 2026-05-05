from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

MAGIC = 0x504F4331  # "POC1"
VERSION = 1
HEADER_BYTES = 48
HEADER_STRUCT = struct.Struct(">IHHIIdddII")


class AudioPacketError(ValueError):
    """Raised when an incoming binary audio packet does not match the wire format."""


@dataclass(frozen=True)
class AudioPacket:
    sequence: int
    tab_id: int
    capture_started_at_ms: float
    chunk_started_at_ms: float
    client_sent_at_ms: float
    sample_rate: int
    sample_count: int
    pcm16: bytes

    @property
    def duration_ms(self) -> float:
        return self.sample_count / self.sample_rate * 1000.0


def parse_audio_packet(message: bytes) -> AudioPacket:
    if len(message) < HEADER_BYTES:
        raise AudioPacketError(f"audio packet too short: {len(message)} bytes")

    (
        magic,
        version,
        header_bytes,
        sequence,
        tab_id,
        capture_started_at_ms,
        chunk_started_at_ms,
        client_sent_at_ms,
        sample_rate,
        sample_count,
    ) = HEADER_STRUCT.unpack_from(message, 0)

    if magic != MAGIC:
        raise AudioPacketError(f"bad audio packet magic: 0x{magic:x}")
    if version != VERSION:
        raise AudioPacketError(f"unsupported audio packet version: {version}")
    if header_bytes != HEADER_BYTES:
        raise AudioPacketError(f"unexpected header size: {header_bytes}")
    if sample_rate <= 0:
        raise AudioPacketError(f"invalid sample rate: {sample_rate}")
    if sample_count <= 0:
        raise AudioPacketError(f"invalid sample count: {sample_count}")

    pcm16 = message[header_bytes:]
    expected_bytes = sample_count * 2
    if len(pcm16) != expected_bytes:
        raise AudioPacketError(
            f"pcm payload size mismatch: expected {expected_bytes} bytes, got {len(pcm16)}"
        )

    return AudioPacket(
        sequence=sequence,
        tab_id=tab_id,
        capture_started_at_ms=capture_started_at_ms,
        chunk_started_at_ms=chunk_started_at_ms,
        client_sent_at_ms=client_sent_at_ms,
        sample_rate=sample_rate,
        sample_count=sample_count,
        pcm16=pcm16,
    )


def build_audio_packet(
    *,
    sequence: int,
    tab_id: int,
    capture_started_at_ms: float,
    chunk_started_at_ms: float,
    client_sent_at_ms: float,
    sample_rate: int,
    pcm16: bytes,
) -> bytes:
    if len(pcm16) % 2 != 0:
        raise AudioPacketError("pcm16 payload must contain complete 16-bit samples")
    sample_count = len(pcm16) // 2
    header = HEADER_STRUCT.pack(
        MAGIC,
        VERSION,
        HEADER_BYTES,
        sequence,
        tab_id,
        capture_started_at_ms,
        chunk_started_at_ms,
        client_sent_at_ms,
        sample_rate,
        sample_count,
    )
    return header + pcm16


def pcm16_to_float32(pcm16: bytes) -> NDArray[np.float32]:
    samples = np.frombuffer(pcm16, dtype="<i2")
    return (samples.astype(np.float32) / 32768.0).clip(-1.0, 1.0)


def audio_levels(samples: NDArray[np.float32]) -> tuple[float, float]:
    if samples.size == 0:
        return 0.0, 0.0
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    peak = float(np.max(np.abs(samples)))
    return rms, peak
