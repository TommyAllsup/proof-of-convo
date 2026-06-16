from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from pathlib import Path
from time import sleep

import pytest

from backend.tts.orchestrator import TtsOrchestrator, TtsSpeechResult
from backend.tts.playback import NullAudioPlayer
from backend.tts.providers import FakeTtsProvider, TtsProviderInfo


@pytest.mark.asyncio
async def test_tts_orchestrator_streams_fake_audio_to_null_player() -> None:
    player = NullAudioPlayer()
    handled_results: list[TtsSpeechResult] = []
    tts = TtsOrchestrator(
        enabled=True,
        playback_enabled=False,
        provider=FakeTtsProvider(),
        player=player,
        queue_max=2,
        result_handler=handled_results.append,
    )
    tts.start()
    try:
        job = tts.enqueue("Please read this concise meeting response.")
        await tts.drain()
    finally:
        await tts.stop()

    stats = tts.stats()
    speeches = tts.recent_speeches()
    assert job.job_id
    assert stats.completed_speeches == 1
    assert stats.processing_errors == 0
    assert stats.total_audio_bytes > 0
    assert player.total_bytes == stats.total_audio_bytes
    assert len(speeches) == 1
    assert speeches[0].ttfa_ms is not None
    assert speeches[0].error is None
    assert speeches[0].dump_path is None
    assert handled_results == speeches


@pytest.mark.asyncio
async def test_tts_orchestrator_dumps_completed_speech(tmp_path: Path) -> None:
    tts = TtsOrchestrator(
        enabled=True,
        playback_enabled=False,
        provider=FakeTtsProvider(),
        player=NullAudioPlayer(),
        queue_max=2,
        dump_dir=tmp_path,
        dump_enabled=True,
    )
    tts.start()
    try:
        tts.enqueue("Dump this voice output.")
        await tts.drain()
    finally:
        await tts.stop()

    speech = tts.recent_speeches()[0]
    assert speech.dump_path is not None
    dump_path = Path(speech.dump_path)
    assert await asyncio.to_thread(dump_path.exists)
    assert dump_path.suffix == ".wav"
    stat = await asyncio.to_thread(dump_path.stat)
    assert stat.st_size > 44


@pytest.mark.asyncio
async def test_tts_orchestrator_rejects_speak_when_disabled() -> None:
    tts = TtsOrchestrator(
        enabled=False,
        playback_enabled=False,
        provider=FakeTtsProvider(),
        player=NullAudioPlayer(),
        queue_max=2,
    )

    with pytest.raises(RuntimeError, match="TTS is disabled"):
        tts.enqueue("hello")


@pytest.mark.asyncio
async def test_tts_orchestrator_interrupts_active_stream() -> None:
    player = NullAudioPlayer()
    provider = SlowChunkProvider()
    tts = TtsOrchestrator(
        enabled=True,
        playback_enabled=False,
        provider=provider,
        player=player,
        queue_max=2,
    )
    tts.start()
    try:
        tts.enqueue("long response")
        started = await asyncio.to_thread(provider.started.wait, 1.0)
        assert started is True
        assert tts.interrupt_current(reason="test_barge_in") is True
        await tts.drain()
    finally:
        await tts.stop()

    stats = tts.stats()
    speeches = tts.recent_speeches()
    assert stats.completed_speeches == 0
    assert stats.interrupted_speeches == 1
    assert speeches[0].interrupted is True
    assert speeches[0].interrupt_reason == "test_barge_in"


class SlowChunkProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.info = TtsProviderInfo(
            provider="slow",
            model_id="slow-test",
            voice_id="slow",
            voice_name="slow",
            sample_rate=24_000,
            encoding="pcm_s16le",
        )

    def stream_speech(self, text: str) -> Iterator[bytes]:
        _ = text
        self.started.set()
        for _ in range(100):
            sleep(0.005)
            yield b"\x00\x00" * 240
