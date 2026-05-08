from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from backend.audio.consumer import EndpointingConsumer
from backend.audio.frames import AudioPacketError, parse_audio_packet
from backend.audio.manager import AudioStreamManager, now_ms
from backend.config import settings
from backend.models.audio import ClientPing, ErrorEvent, SessionAck, SessionStart, SessionStop

logger = logging.getLogger("proof.backend")


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


manager = AudioStreamManager(
    queue_max=settings.audio_queue_max,
    dump_dir=settings.audio_dump_dir,
    dump_seconds=settings.audio_dump_seconds,
    telemetry_dir=settings.telemetry_dir,
    telemetry_enabled=settings.telemetry_enabled,
)
audio_consumer = EndpointingConsumer(manager.queue, vad_provider_name=settings.vad_provider)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    audio_consumer.start()
    logger.info("backend_start host=%s port=%s", settings.host, settings.port)
    try:
        yield
    finally:
        await audio_consumer.stop()
        manager.close_all()
        logger.info("backend_stop")


app = FastAPI(title="Proof of Conversation Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "proof-of-convo-backend",
        "active_sessions": len(manager.list_sessions()),
        "audio_queue_depth": manager.queue.qsize(),
        "audio_consumer": asdict(audio_consumer.stats()),
    }


@app.get("/api/sessions")
async def sessions() -> dict[str, Any]:
    return {"sessions": [session.model_dump() for session in manager.list_sessions()]}


@app.get("/api/audio/consumer")
async def audio_consumer_status() -> dict[str, Any]:
    return {
        "stats": asdict(audio_consumer.stats()),
        "recent_endpoint_events": [
            {
                "type": event.type,
                "session_id": event.session_id,
                "sequence": event.sequence,
                "event_ms": event.event_ms,
                "segment": asdict(event.segment) if event.segment is not None else None,
            }
            for event in audio_consumer.recent_events()
        ],
    }


async def _send_error(websocket: WebSocket, message: str) -> None:
    event = ErrorEvent(message=message, received_at_ms=now_ms())
    await websocket.send_text(event.model_dump_json())


async def _handle_text_message(
    websocket: WebSocket, text: str, session_id: str | None
) -> str | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        await _send_error(websocket, f"invalid json message: {exc.msg}")
        return session_id

    message_type = payload.get("type")
    received_at_ms = now_ms()

    if message_type == "session_start":
        try:
            start = SessionStart.model_validate(payload)
        except ValidationError as exc:
            await _send_error(websocket, f"invalid session_start: {exc}")
            return session_id

        stats = manager.start_session(start)
        logger.info(
            "session_start session_id=%s tab_id=%s sample_rate=%s meeting_url=%s",
            stats.session_id,
            stats.tab_id,
            stats.sample_rate,
            stats.meeting_url,
        )
        ack = SessionAck(
            session_id=start.session_id,
            received_at_ms=received_at_ms,
            sample_rate=start.sample_rate,
            dump_path=stats.dump_path,
            telemetry_session_path=stats.telemetry_session_path,
            telemetry_chunks_path=stats.telemetry_chunks_path,
        )
        await websocket.send_text(ack.model_dump_json())
        return start.session_id

    if message_type == "session_stop":
        try:
            stop = SessionStop.model_validate(payload)
        except ValidationError as exc:
            await _send_error(websocket, f"invalid session_stop: {exc}")
            return session_id
        stop_stats = manager.stop_session(stop.session_id, reason=stop.reason)
        logger.info(
            "session_stop session_id=%s reason=%s total_chunks=%s dropped_chunks=%s",
            stop.session_id,
            stop.reason,
            stop_stats.total_chunks if stop_stats else None,
            stop_stats.dropped_chunks if stop_stats else None,
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "session_stopped",
                    "session_id": stop.session_id,
                    "received_at_ms": received_at_ms,
                    "stats": stop_stats.model_dump() if stop_stats else None,
                }
            )
        )
        return None if session_id == stop.session_id else session_id

    if message_type == "ping":
        ping = ClientPing.model_validate(payload)
        await websocket.send_text(
            json.dumps(
                {
                    "type": "pong",
                    "session_id": ping.session_id,
                    "client_sent_at_ms": ping.client_sent_at_ms,
                    "received_at_ms": received_at_ms,
                }
            )
        )
        return session_id

    await _send_error(websocket, f"unknown message type: {message_type}")
    return session_id


@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id: str | None = None
    last_ack_sent_at_ms = 0.0
    logger.info("audio_ws_connect client=%s", websocket.client)

    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break

            if text := message.get("text"):
                session_id = await _handle_text_message(websocket, text, session_id)
                continue

            payload = message.get("bytes")
            if payload is None:
                continue

            if session_id is None:
                await _send_error(websocket, "binary audio received before session_start")
                continue

            received_at_ms = now_ms()
            try:
                packet = parse_audio_packet(payload)
                ack = await manager.ingest_packet(
                    session_id=session_id,
                    packet=packet,
                    received_at_ms=received_at_ms,
                )
            except AudioPacketError as exc:
                await _send_error(websocket, str(exc))
                continue

            should_ack = (
                ack.sequence == 0
                or ack.sequence % 5 == 0
                or received_at_ms - last_ack_sent_at_ms >= 500.0
            )
            if should_ack:
                await websocket.send_text(ack.model_dump_json())
                last_ack_sent_at_ms = received_at_ms

            logger.debug(
                "audio_chunk session_id=%s sequence=%s latency_ms=%s rms=%.5f peak=%.5f",
                session_id,
                ack.sequence,
                f"{ack.latency_ms:.1f}" if ack.latency_ms is not None else None,
                ack.rms,
                ack.peak,
            )
    except WebSocketDisconnect:
        pass
    finally:
        if session_id is not None:
            manager.stop_session(session_id, reason="websocket_disconnect")
        logger.info("audio_ws_disconnect client=%s session_id=%s", websocket.client, session_id)


def run() -> None:
    import uvicorn

    configure_logging()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
