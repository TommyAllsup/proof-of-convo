from __future__ import annotations

import numpy as np
import pytest

from backend.audio.frames import (
    AudioPacketError,
    audio_levels,
    build_audio_packet,
    parse_audio_packet,
    pcm16_to_float32,
)


def test_audio_packet_round_trip() -> None:
    pcm16 = np.array([0, 1000, -1000, 32767, -32768], dtype="<i2").tobytes()
    packet = build_audio_packet(
        sequence=42,
        tab_id=123,
        capture_started_at_ms=10.0,
        chunk_started_at_ms=20.0,
        client_sent_at_ms=30.0,
        sample_rate=16_000,
        pcm16=pcm16,
    )

    parsed = parse_audio_packet(packet)

    assert parsed.sequence == 42
    assert parsed.tab_id == 123
    assert parsed.sample_rate == 16_000
    assert parsed.sample_count == 5
    assert parsed.pcm16 == pcm16
    assert parsed.source == "unknown"


def test_audio_packet_round_trip_with_source() -> None:
    pcm16 = np.array([0, 1000, -1000], dtype="<i2").tobytes()
    packet = build_audio_packet(
        sequence=7,
        tab_id=321,
        capture_started_at_ms=10.0,
        chunk_started_at_ms=20.0,
        client_sent_at_ms=30.0,
        sample_rate=16_000,
        pcm16=pcm16,
        source="mic",
    )

    parsed = parse_audio_packet(packet)

    assert parsed.sequence == 7
    assert parsed.tab_id == 321
    assert parsed.sample_count == 3
    assert parsed.source == "mic"
    assert parsed.pcm16 == pcm16


def test_audio_packet_rejects_bad_payload_size() -> None:
    packet = build_audio_packet(
        sequence=0,
        tab_id=0,
        capture_started_at_ms=0.0,
        chunk_started_at_ms=0.0,
        client_sent_at_ms=0.0,
        sample_rate=16_000,
        pcm16=np.zeros(4, dtype="<i2").tobytes(),
    )

    with pytest.raises(AudioPacketError, match="pcm payload size mismatch"):
        parse_audio_packet(packet[:-1])


def test_pcm_levels() -> None:
    pcm16 = np.array([0, 32767, -32768], dtype="<i2").tobytes()

    samples = pcm16_to_float32(pcm16)
    rms, peak = audio_levels(samples)

    assert samples.dtype == np.float32
    assert peak == pytest.approx(1.0)
    assert rms > 0.8
