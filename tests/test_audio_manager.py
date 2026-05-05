from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.audio.frames import build_audio_packet, parse_audio_packet
from backend.audio.manager import AudioStreamManager
from backend.models.audio import SessionStart


@pytest.mark.asyncio
async def test_audio_manager_tracks_stats_and_sequence_gaps(tmp_path: Path) -> None:
    manager = AudioStreamManager(queue_max=4, dump_dir=tmp_path, dump_seconds=1)
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

    stopped = manager.stop_session("session-1")

    assert stopped is not None
    assert tmp_path.joinpath("session-1_first_1s.wav").exists()
