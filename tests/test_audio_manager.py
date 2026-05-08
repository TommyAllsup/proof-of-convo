from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from backend.audio.frames import build_audio_packet, parse_audio_packet
from backend.audio.manager import AudioStreamManager
from backend.models.audio import SessionStart


@pytest.mark.asyncio
async def test_audio_manager_tracks_stats_and_sequence_gaps(tmp_path: Path) -> None:
    manager = AudioStreamManager(
        queue_max=4,
        dump_dir=tmp_path / "audio",
        dump_seconds=1,
        telemetry_dir=tmp_path / "telemetry",
    )
    manager.start_session(
        SessionStart(
            type="session_start",
            session_id="session-1",
            tab_id=99,
            sample_rate=16_000,
        )
    )

    pcm16 = np.zeros(1600, dtype="<i2").tobytes()
    for sequence in [0, 2]:
        packet = parse_audio_packet(
            build_audio_packet(
                sequence=sequence,
                tab_id=99,
                capture_started_at_ms=100.0,
                chunk_started_at_ms=200.0,
                client_sent_at_ms=300.0,
                sample_rate=16_000,
                pcm16=pcm16,
            )
        )
        ack = await manager.ingest_packet(
            session_id="session-1",
            packet=packet,
            received_at_ms=350.0 + sequence,
        )

    stats = manager.get_session("session-1")

    assert stats is not None
    assert ack.sequence == 2
    assert stats.total_chunks == 2
    assert stats.dropped_chunks == 1
    assert stats.last_latency_ms == pytest.approx(52.0)
    assert stats.dump_path is not None
    assert stats.telemetry_session_path is not None
    assert stats.telemetry_chunks_path is not None

    stopped = manager.stop_session("session-1")

    assert stopped is not None
    assert tmp_path.joinpath("audio/session-1_first_1s.wav").exists()

    session_path = tmp_path / "telemetry/session-1_session.json"
    chunks_path = tmp_path / "telemetry/session-1_chunks.jsonl"
    assert session_path.exists()
    assert chunks_path.exists()

    session_payload = json.loads(session_path.read_text(encoding="utf-8"))
    chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]

    assert session_payload["type"] == "session_stopped"
    assert session_payload["stats"]["total_chunks"] == 2
    assert session_payload["stats"]["dropped_chunks"] == 1
    assert len(chunks) == 2
    assert chunks[0]["sequence"] == 0
    assert chunks[1]["sequence"] == 2
    assert chunks[1]["latency_ms"] == pytest.approx(52.0)


@pytest.mark.asyncio
async def test_audio_manager_skips_telemetry_when_session_disables_it(tmp_path: Path) -> None:
    manager = AudioStreamManager(
        queue_max=4,
        dump_dir=tmp_path / "audio",
        dump_seconds=0,
        telemetry_dir=tmp_path / "telemetry",
    )
    manager.start_session(
        SessionStart(
            type="session_start",
            session_id="session-no-telemetry",
            sample_rate=16_000,
            telemetry_enabled=False,
        )
    )

    packet = parse_audio_packet(
        build_audio_packet(
            sequence=0,
            tab_id=99,
            capture_started_at_ms=100.0,
            chunk_started_at_ms=200.0,
            client_sent_at_ms=300.0,
            sample_rate=16_000,
            pcm16=np.zeros(1600, dtype="<i2").tobytes(),
        )
    )
    await manager.ingest_packet(
        session_id="session-no-telemetry",
        packet=packet,
        received_at_ms=350.0,
    )

    stopped = manager.stop_session("session-no-telemetry")

    assert stopped is not None
    assert stopped.telemetry_session_path is None
    assert stopped.telemetry_chunks_path is None
    assert not (tmp_path / "telemetry").exists()


@pytest.mark.asyncio
async def test_audio_manager_skips_telemetry_when_global_flag_disables_it(tmp_path: Path) -> None:
    manager = AudioStreamManager(
        queue_max=4,
        dump_dir=tmp_path / "audio",
        dump_seconds=0,
        telemetry_dir=tmp_path / "telemetry",
        telemetry_enabled=False,
    )
    stats = manager.start_session(
        SessionStart(
            type="session_start",
            session_id="session-global-disabled",
            sample_rate=16_000,
        )
    )

    assert stats.telemetry_session_path is None
    assert stats.telemetry_chunks_path is None
    assert not (tmp_path / "telemetry").exists()


@pytest.mark.asyncio
async def test_audio_manager_queues_chunks_with_computed_levels(tmp_path: Path) -> None:
    manager = AudioStreamManager(
        queue_max=4,
        dump_dir=tmp_path / "audio",
        dump_seconds=0,
        telemetry_dir=tmp_path / "telemetry",
    )
    pcm16 = np.full(1600, 1000, dtype="<i2").tobytes()
    packet = parse_audio_packet(
        build_audio_packet(
            sequence=0,
            tab_id=99,
            capture_started_at_ms=100.0,
            chunk_started_at_ms=200.0,
            client_sent_at_ms=300.0,
            sample_rate=16_000,
            pcm16=pcm16,
        )
    )

    ack = await manager.ingest_packet(
        session_id="session-levels",
        packet=packet,
        received_at_ms=350.0,
    )
    event = manager.queue.get_nowait()
    manager.queue.task_done()

    assert event.rms == pytest.approx(ack.rms)
    assert event.peak == pytest.approx(ack.peak)
    assert event.rms > 0


@pytest.mark.asyncio
async def test_audio_manager_marks_evicted_queue_items_done(tmp_path: Path) -> None:
    manager = AudioStreamManager(
        queue_max=1,
        dump_dir=tmp_path / "audio",
        dump_seconds=0,
        telemetry_dir=tmp_path / "telemetry",
    )

    for sequence in range(2):
        packet = parse_audio_packet(
            build_audio_packet(
                sequence=sequence,
                tab_id=99,
                capture_started_at_ms=100.0,
                chunk_started_at_ms=200.0 + sequence * 100.0,
                client_sent_at_ms=300.0,
                sample_rate=16_000,
                pcm16=np.zeros(1600, dtype="<i2").tobytes(),
            )
        )
        await manager.ingest_packet(
            session_id="session-evict",
            packet=packet,
            received_at_ms=350.0,
        )

    event = manager.queue.get_nowait()
    manager.queue.task_done()

    assert event.packet.sequence == 1
    await asyncio.wait_for(manager.queue.join(), timeout=1.0)
