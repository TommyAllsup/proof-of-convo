from __future__ import annotations

import argparse
import asyncio
import json
import signal
import time
import uuid

import sounddevice as sd
import websockets

from backend.audio.frames import build_audio_packet


async def capture_local_mic(
    *,
    url: str,
    device: int | None,
    session_id: str,
    sample_rate: int,
    chunk_ms: int,
) -> None:
    started_at_ms = time.time() * 1000.0
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def stop() -> None:
        stop_event.set()

    for signame in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, signame), stop)
        except NotImplementedError:
            pass

    def callback(indata: bytes, frames: int, _time, status: sd.CallbackFlags) -> None:
        if status:
            print(f"mic callback status: {status}", flush=True)
        payload = bytes(indata)
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except asyncio.QueueFull:
            pass

    blocksize = sample_rate * chunk_ms // 1000
    async with websockets.connect(url, max_size=None) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "session_start",
                    "session_id": session_id,
                    "tab_id": 0,
                    "meeting_url": "local://microphone#source=mic",
                    "sample_rate": sample_rate,
                    "chunk_ms": chunk_ms,
                    "client_started_at_ms": started_at_ms,
                    "client_sent_at_ms": time.time() * 1000.0,
                    "telemetry_enabled": True,
                    "audio_source": "mic",
                }
            )
        )
        print(await websocket.recv(), flush=True)

        sequence = 0
        with sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=blocksize,
            device=device,
            channels=1,
            dtype="int16",
            callback=callback,
        ):
            while not stop_event.is_set():
                pcm16 = await queue.get()
                sent_at_ms = time.time() * 1000.0
                packet = build_audio_packet(
                    sequence=sequence,
                    tab_id=0,
                    capture_started_at_ms=started_at_ms,
                    chunk_started_at_ms=sent_at_ms - chunk_ms,
                    client_sent_at_ms=sent_at_ms,
                    sample_rate=sample_rate,
                    pcm16=pcm16,
                    source="mic",
                )
                await websocket.send(packet)
                sequence += 1
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=0.001)
                except TimeoutError:
                    message = None
                if message:
                    print(message, flush=True)

        await websocket.send(
            json.dumps(
                {
                    "type": "session_stop",
                    "session_id": session_id,
                    "reason": "local_mic_capture_stopped",
                    "client_sent_at_ms": time.time() * 1000.0,
                }
            )
        )
        print(await websocket.recv(), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture local microphone into backend audio WS.")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/audio")
    parser.add_argument("--device", type=int, default=None)
    parser.add_argument("--session-id", default=f"local-mic-{uuid.uuid4()}:mic")
    parser.add_argument("--sample-rate", type=int, default=16_000)
    parser.add_argument("--chunk-ms", type=int, default=200)
    args = parser.parse_args()

    asyncio.run(
        capture_local_mic(
            url=args.url,
            device=args.device,
            session_id=args.session_id,
            sample_rate=args.sample_rate,
            chunk_ms=args.chunk_ms,
        )
    )


if __name__ == "__main__":
    main()
