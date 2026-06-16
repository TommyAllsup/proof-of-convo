from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

MAGIC = 0x504F4331  # "POC1"
VERSION = 2
HEADER_BYTES_V1 = 48
HEADER_BYTES_V2 = 52
HEADER_BYTES = HEADER_BYTES_V2
HEADER_STRUCT_V1 = struct.Struct(">IHHIIdddII")
HEADER_STRUCT_V2 = struct.Struct(">IHHIIdddIIBxxx")

SOURCE_IDS = {
    0: "unknown",
    1: "tab",
    2: "mic",
}
SOURCE_NAMES = {value: key for key, value in SOURCE_IDS.items()}


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
    source: str = "unknown"

    @property
    def duration_ms(self) -> float:
        return self.sample_count / self.sample_rate * 1000.0


def parse_audio_packet(message: bytes) -> AudioPacket:
    if len(message) < HEADER_BYTES_V1:
        raise AudioPacketError(f"audio packet too short: {len(message)} bytes")

    (
        magic,
        version,
        header_bytes,
    ) = struct.Struct(">IHH").unpack_from(message, 0)

    if version == 1:
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
        ) = HEADER_STRUCT_V1.unpack_from(message, 0)
        source = "unknown"
    elif version == VERSION:
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
            source_id,
        ) = HEADER_STRUCT_V2.unpack_from(message, 0)
        if source_id not in SOURCE_IDS:
            raise AudioPacketError(f"unknown audio source id: {source_id}")
        source = SOURCE_IDS[source_id]
    else:
        raise AudioPacketError(f"unsupported audio packet version: {version}")

    (
        _magic,
        _version,
        _header_bytes,
        sequence,
        tab_id,
        capture_started_at_ms,
        chunk_started_at_ms,
        client_sent_at_ms,
        sample_rate,
        sample_count,
    ) = (
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
    )

    if magic != MAGIC:
        raise AudioPacketError(f"bad audio packet magic: 0x{magic:x}")
    if header_bytes not in {HEADER_BYTES_V1, HEADER_BYTES_V2}:
        raise AudioPacketError(f"unexpected header size: {header_bytes}")
    if version == 1 and header_bytes != HEADER_BYTES_V1:
        raise AudioPacketError(f"unexpected v1 header size: {header_bytes}")
    if version == VERSION and header_bytes != HEADER_BYTES_V2:
        raise AudioPacketError(f"unexpected v2 header size: {header_bytes}")
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
        source=source,
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
    source: str = "unknown",
) -> bytes:
    if len(pcm16) % 2 != 0:
        raise AudioPacketError("pcm16 payload must contain complete 16-bit samples")
    sample_count = len(pcm16) // 2
    source_id = SOURCE_NAMES.get(source)
    if source_id is None:
        raise AudioPacketError(f"unknown audio source: {source}")
    header = HEADER_STRUCT_V2.pack(
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
        source_id,
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
