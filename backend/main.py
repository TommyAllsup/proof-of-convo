from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from backend.agent import MeetingAgentOrchestrator, create_llm_client
from backend.audio.consumer import EndpointingConsumer
from backend.audio.diarization import SpeakerAttribution
from backend.audio.endpointing import EndpointEvent
from backend.audio.frames import AudioPacketError, parse_audio_packet
from backend.audio.live_stt import LiveSttOrchestrator, LiveTranscript
from backend.audio.manager import AudioStreamManager, now_ms
from backend.audio.stt import SttTranscript
from backend.audio.stt_windows import UtteranceWindow
from backend.config import settings
from backend.models.agent import (
    AgentApplyCandidateRequest,
    AgentBeginMeetingRequest,
    AgentDismissCandidateRequest,
    AgentEndMeetingRequest,
    AgentInjectTranscriptRequest,
    AgentLifecycleResponse,
    AgentModeRequest,
    AgentReadiness,
    AgentSettings,
    AgentSettingsRequest,
    AgentSpeakCandidateRequest,
)
from backend.models.audio import (
    ClientPing,
    ErrorEvent,
    SessionAck,
    SessionStart,
    SessionStop,
    SpeakerLabelRequest,
    Utterance,
)
from backend.models.tts import TtsInterruptResponse, TtsSpeakRequest, TtsSpeakResponse
from backend.tts import TtsOrchestrator, create_audio_player, create_tts_provider
from backend.tts.orchestrator import TtsSpeechResult
from backend.tts.playback import list_output_devices

logger = logging.getLogger("proof.backend")


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _tts_api_key(provider_name: str) -> str | None:
    normalized = provider_name.strip().lower()
    if normalized == "elevenlabs":
        return settings.elevenlabs_api_key
    if normalized == "cartesia":
        return settings.cartesia_api_key
    return None


def _tts_base_url(provider_name: str) -> str | None:
    normalized = provider_name.strip().lower()
    if normalized == "elevenlabs":
        return settings.elevenlabs_base_url
    if normalized == "cartesia":
        return settings.cartesia_base_url
    return None


manager = AudioStreamManager(
    queue_max=settings.audio_queue_max,
    dump_dir=settings.audio_dump_dir,
    dump_seconds=settings.audio_dump_seconds,
    telemetry_dir=settings.telemetry_dir,
    telemetry_enabled=settings.telemetry_enabled,
)
agent = MeetingAgentOrchestrator(
    summary_dir=settings.agent_summary_dir,
    llm_client=create_llm_client(
        settings.agent_llm_provider,
        api_key=settings.openai_api_key,
        model=settings.agent_llm_model,
        base_url=settings.agent_llm_base_url,
        timeout_s=settings.agent_llm_timeout_s,
        max_output_tokens=settings.agent_llm_max_output_tokens,
        reasoning_prompt_suffix=settings.agent_llm_reasoning_prompt_suffix,
        direct_answer_prompt_suffix=settings.agent_llm_direct_answer_prompt_suffix,
        context_summary_prompt_suffix=settings.agent_llm_context_summary_prompt_suffix,
    ),
)
tts_provider = create_tts_provider(
    settings.tts_provider,
    api_key=_tts_api_key(settings.tts_provider),
    voice_id=settings.tts_voice_id,
    voice_name=settings.tts_voice_name,
    model_id=settings.tts_model,
    base_url=_tts_base_url(settings.tts_provider),
    output_format=settings.tts_output_format,
    sample_rate=settings.tts_sample_rate,
    speaking_rate=settings.tts_speaking_rate,
    chunk_size_bytes=settings.tts_chunk_size_bytes,
    cartesia_version=settings.cartesia_version,
)
tts = TtsOrchestrator(
    enabled=settings.tts_enabled,
    playback_enabled=settings.tts_playback_enabled,
    provider=tts_provider,
    player=create_audio_player(
        playback_enabled=settings.tts_playback_enabled,
        output_device=settings.tts_output_device,
    ),
    queue_max=settings.tts_queue_max,
    dump_dir=settings.tts_dump_dir,
    dump_enabled=settings.tts_dump_enabled,
    result_handler=lambda result: agent.observe_speech_result(
        job_id=result.job_id,
        completed_at_ms=result.completed_at_ms,
        error=result.error,
        interrupted=result.interrupted,
    ),
)
live_stt = LiveSttOrchestrator(
    enabled=settings.stt_enabled,
    provider_name=settings.stt_provider,
    model_id=settings.stt_model,
    language=settings.stt_language,
    vad_provider_name=settings.vad_provider,
    diarization_provider_name=settings.diarization_provider,
    queue_max=settings.stt_queue_max,
    buffer_history_ms=settings.stt_buffer_history_ms,
    pre_roll_ms=settings.stt_pre_roll_ms,
    post_roll_ms=settings.stt_post_roll_ms,
    transcript_handler=lambda transcript: agent.observe_transcript(transcript, speaker=tts),
)


def _handle_endpoint_event(event: EndpointEvent) -> None:
    live_stt.handle_endpoint(event)
    _refresh_agent_readiness()
    if event.type == "speech_start":
        agent.observe_human_speech_start(event.event_ms)
        tts.interrupt_current(reason="human_speech")
    elif event.type == "speech_end":
        agent.observe_silence(event.event_ms, speaker=tts)


audio_consumer = EndpointingConsumer(
    manager.queue,
    vad_provider_name=settings.vad_provider,
    chunk_handler=live_stt.observe_chunk,
    endpoint_handler=_handle_endpoint_event,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    live_stt.start()
    audio_consumer.start()
    tts.start()
    logger.info("backend_start host=%s port=%s", settings.host, settings.port)
    try:
        yield
    finally:
        await tts.stop()
        await audio_consumer.stop()
        await live_stt.stop()
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
        "stt_worker": asdict(live_stt.stats()),
        "tts_worker": asdict(tts.stats()),
        "agent": _agent_status_payload(),
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


@app.get("/api/stt")
async def stt_status() -> dict[str, Any]:
    return {
        "stats": asdict(live_stt.stats()),
        "recent_transcripts": [
            _live_transcript_payload(item) for item in live_stt.recent_transcripts()
        ],
    }


@app.post("/api/stt/speakers/label")
async def label_stt_speaker(request: SpeakerLabelRequest) -> dict[str, Any]:
    live_stt.set_speaker_label(
        session_id=request.session_id,
        speaker=request.speaker,
        label=request.label,
    )
    return {
        "ok": True,
        "session_id": request.session_id,
        "speaker": request.speaker,
        "label": request.label.strip() if request.label else None,
    }


def _live_transcript_payload(item: LiveTranscript) -> dict[str, Any]:
    return {
        "completed_at_ms": item.completed_at_ms,
        "window": asdict(item.window),
        "speaker": asdict(item.speaker),
        "utterance": item.utterance.model_dump(mode="json"),
        "transcript": asdict(item.transcript),
    }


@app.get("/api/tts")
async def tts_status() -> dict[str, Any]:
    return {
        "stats": asdict(tts.stats()),
        "recent_speeches": [_tts_speech_payload(item) for item in tts.recent_speeches()],
    }


@app.get("/api/agent")
async def agent_status() -> dict[str, Any]:
    return {"status": _agent_status_payload()}


@app.post("/api/agent/mode")
async def set_agent_mode(request: AgentModeRequest) -> AgentLifecycleResponse:
    return AgentLifecycleResponse(status=agent.set_mode(request.mode))


@app.post("/api/agent/settings")
async def set_agent_settings(request: AgentSettingsRequest) -> AgentLifecycleResponse:
    current = agent.status().settings
    return AgentLifecycleResponse(
        status=agent.set_settings(
            AgentSettings(
                aggressiveness=request.aggressiveness,
                direct_answer_cooldown_ms=(
                    request.direct_answer_cooldown_ms
                    if request.direct_answer_cooldown_ms is not None
                    else current.direct_answer_cooldown_ms
                ),
                proactive_min_silence_ms=(
                    request.proactive_min_silence_ms
                    if request.proactive_min_silence_ms is not None
                    else current.proactive_min_silence_ms
                ),
            )
        )
    )


@app.post("/api/agent/meeting/begin")
async def begin_agent_meeting(request: AgentBeginMeetingRequest) -> AgentLifecycleResponse:
    return AgentLifecycleResponse(status=agent.begin_meeting(request))


@app.post("/api/agent/meeting/end")
async def end_agent_meeting(_: AgentEndMeetingRequest) -> AgentLifecycleResponse:
    return AgentLifecycleResponse(status=agent.end_meeting())


@app.get("/api/agent/summary")
async def agent_summary() -> dict[str, Any]:
    summary = agent.latest_summary()
    if summary is None:
        raise HTTPException(status_code=404, detail="summary not available")
    return {"summary": summary.model_dump(mode="json")}


@app.get("/api/agent/summary.md")
async def agent_summary_markdown() -> Response:
    summary = agent.latest_summary()
    if summary is None:
        raise HTTPException(status_code=404, detail="summary not available")
    return Response(content=summary.markdown, media_type="text/markdown")


@app.post("/api/agent/candidates/speak")
async def speak_agent_candidate(request: AgentSpeakCandidateRequest) -> AgentLifecycleResponse:
    candidate = agent.speak_candidate(
        request.candidate_id,
        speaker=tts,
        interrupt=request.interrupt,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return AgentLifecycleResponse(status=agent.status())


@app.post("/api/agent/candidates/dismiss")
async def dismiss_agent_candidate(
    request: AgentDismissCandidateRequest,
) -> AgentLifecycleResponse:
    candidate = agent.dismiss_candidate(request.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return AgentLifecycleResponse(status=agent.status())


@app.post("/api/agent/candidates/apply")
async def apply_agent_candidate(request: AgentApplyCandidateRequest) -> AgentLifecycleResponse:
    candidate = agent.apply_candidate(request.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not applicable")
    return AgentLifecycleResponse(status=agent.status())


@app.post("/api/agent/transcript")
async def inject_agent_transcript(request: AgentInjectTranscriptRequest) -> AgentLifecycleResponse:
    if agent.status().lifecycle_state == "not_in_meeting":
        agent.begin_meeting(
            AgentBeginMeetingRequest(
                meeting_id=request.session_id or "manual-agent-session",
                meeting_url="manual://agent-transcript",
            )
        )
    transcript = _manual_live_transcript(request)
    agent.observe_transcript(transcript, speaker=tts)
    return AgentLifecycleResponse(status=agent.status())


@app.post("/api/tts/speak")
async def speak(request: TtsSpeakRequest) -> TtsSpeakResponse:
    try:
        job = tts.enqueue(request.text, interrupt=request.interrupt)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TtsSpeakResponse(job_id=job.job_id, queued_at_ms=job.queued_at_ms, text=job.text)


@app.post("/api/tts/interrupt")
async def interrupt_tts() -> TtsInterruptResponse:
    interrupted = tts.interrupt_current(reason="manual_stop")
    return TtsInterruptResponse(
        interrupted=interrupted,
        reason="manual_stop",
        received_at_ms=now_ms(),
    )


@app.get("/api/audio/devices")
async def audio_devices() -> dict[str, Any]:
    try:
        devices = list_output_devices()
    except Exception as exc:  # noqa: BLE001 - depends on local PortAudio host state.
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "output_devices": []}
    return {"ok": True, "output_devices": [asdict(device) for device in devices]}


def _tts_speech_payload(item: TtsSpeechResult) -> dict[str, Any]:
    return asdict(item)


def _manual_live_transcript(request: AgentInjectTranscriptRequest) -> LiveTranscript:
    current_ms = now_ms()
    start_ms = request.start_ms if request.start_ms is not None else current_ms
    end_ms = request.end_ms if request.end_ms is not None else start_ms + 750.0
    if end_ms < start_ms:
        raise HTTPException(
            status_code=422,
            detail="end_ms must be greater than or equal to start_ms",
        )

    status = agent.status()
    session_id = request.session_id or status.meeting_id or "manual-agent-session"
    utterance_id = request.utterance_id or f"manual-{int(current_ms)}"
    source = "manual://agent-transcript"
    duration_ms = end_ms - start_ms
    window = UtteranceWindow(
        window_id=utterance_id,
        session_id=session_id,
        source_wav=source,
        sample_rate=16_000,
        vad_provider="manual",
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=duration_ms,
        padded_start_ms=start_ms,
        padded_end_ms=end_ms,
        padded_duration_ms=duration_ms,
        start_sequence=0,
        end_sequence=0,
        peak=0.0,
        mean_rms=0.0,
    )
    stt_transcript = SttTranscript(
        window_id=utterance_id,
        provider="manual",
        model_id="manual",
        text=request.text,
        language="en",
        confidence=request.confidence,
        wall_time_s=0.0,
    )
    utterance = Utterance(
        utterance_id=utterance_id,
        session_id=session_id,
        speaker=request.speaker,
        start_ts=start_ms / 1000.0,
        end_ts=end_ms / 1000.0,
        start_ms=start_ms,
        end_ms=end_ms,
        text=request.text,
        is_final=True,
        confidence=request.confidence,
        speaker_confidence=1.0,
        stt_provider="manual",
        stt_model="manual",
        vad_provider="manual",
        raw_audio_ref=source,
    )
    return LiveTranscript(
        window=window,
        transcript=stt_transcript,
        speaker=SpeakerAttribution(speaker=request.speaker, confidence=1.0, method="manual"),
        utterance=utterance,
        completed_at_ms=current_ms,
    )


def _agent_status_payload() -> dict[str, Any]:
    _refresh_agent_readiness()
    return agent.status().model_dump(mode="json")


def _refresh_agent_readiness() -> None:
    blockers: list[str] = []
    if not manager.list_sessions():
        blockers.append("capture inactive")

    consumer_stats = audio_consumer.stats()
    if not consumer_stats.running:
        blockers.append("audio consumer stopped")
    if consumer_stats.last_error is not None:
        blockers.append("audio consumer error")

    stt_stats = live_stt.stats()
    if not stt_stats.enabled:
        blockers.append("stt disabled")
    elif not stt_stats.running:
        blockers.append("stt stopped")
    if stt_stats.last_error is not None:
        blockers.append("stt error")

    tts_stats = tts.stats()
    if not tts_stats.enabled:
        blockers.append("tts disabled")
    elif not tts_stats.running:
        blockers.append("tts stopped")
    if tts_stats.last_error is not None:
        blockers.append("tts error")

    agent.set_readiness(AgentReadiness(can_auto_speak=not blockers, blockers=blockers))


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
        agent.observe_session_start(session_id=start.session_id, meeting_url=start.meeting_url)
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
        agent.observe_session_stop()
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
            agent.observe_session_stop()
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
