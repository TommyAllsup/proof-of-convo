from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
import uuid

import numpy as np
import websockets

from backend.audio.frames import build_audio_packet


def _pcm_sine(sample_rate: int, chunk_ms: int, frequency_hz: float, elapsed_s: float) -> bytes:
    sample_count = sample_rate * chunk_ms // 1000
    start = int(elapsed_s * sample_rate)
    index = np.arange(start, start + sample_count, dtype=np.float64)
    wave = 0.35 * np.sin(2.0 * math.pi * frequency_hz * index / sample_rate)
    return (wave * 32767.0).astype("<i2").tobytes()


async def send_test_audio(
    *,
    url: str,
    duration_s: float,
    sample_rate: int,
    chunk_ms: int,
    frequency_hz: float,
) -> None:
    session_id = f"test-{uuid.uuid4()}"
    started_at_ms = time.time() * 1000.0
    async with websockets.connect(url, max_size=None) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "session_start",
                    "session_id": session_id,
                    "tab_id": 0,
                    "meeting_url": "synthetic://sine",
                    "sample_rate": sample_rate,
                    "chunk_ms": chunk_ms,
                    "client_started_at_ms": started_at_ms,
                    "client_sent_at_ms": time.time() * 1000.0,
                }
            )
        )
        print(await websocket.recv())

        chunks = int(duration_s * 1000 // chunk_ms)
        for sequence in range(chunks):
            elapsed_s = sequence * chunk_ms / 1000.0
            pcm16 = _pcm_sine(sample_rate, chunk_ms, frequency_hz, elapsed_s)
            sent_at_ms = time.time() * 1000.0
            packet = build_audio_packet(
                sequence=sequence,
                tab_id=0,
                capture_started_at_ms=started_at_ms,
                chunk_started_at_ms=sent_at_ms - chunk_ms,
                client_sent_at_ms=sent_at_ms,
                sample_rate=sample_rate,
                pcm16=pcm16,
            )
            await websocket.send(packet)
            await asyncio.sleep(chunk_ms / 1000.0)
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=0.001)
            except TimeoutError:
                message = None
            if message:
                print(message)

        await websocket.send(
            json.dumps(
                {
                    "type": "session_stop",
                    "session_id": session_id,
                    "reason": "synthetic_complete",
                    "client_sent_at_ms": time.time() * 1000.0,
                }
            )
        )
        print(await websocket.recv())


def main() -> None:
    parser = argparse.ArgumentParser(description="Send synthetic PCM16 audio to the backend.")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/audio")
    parser.add_argument("--duration-s", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=int, default=16_000)
    parser.add_argument("--chunk-ms", type=int, default=200)
    parser.add_argument("--frequency-hz", type=float, default=440.0)
    args = parser.parse_args()

    asyncio.run(
        send_test_audio(
            url=args.url,
            duration_s=args.duration_s,
            sample_rate=args.sample_rate,
            chunk_ms=args.chunk_ms,
            frequency_hz=args.frequency_hz,
        )
    )


if __name__ == "__main__":
    main()
