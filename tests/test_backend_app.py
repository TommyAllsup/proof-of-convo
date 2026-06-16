from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend import main as backend_main
from backend.audio.endpointing import EndpointEvent
from backend.models.agent import AgentInjectTranscriptRequest

app = backend_main.app


def test_health_endpoint() -> None:
    backend_main.agent.reset()
    with TestClient(app) as client:
        response = client.get("/health")
        consumer_response = client.get("/api/audio/consumer")
        stt_response = client.get("/api/stt")
        stt_label_response = client.post(
            "/api/stt/speakers/label",
            json={"session_id": "test-meeting", "speaker": "Speaker_1", "label": "Avery"},
        )
        tts_response = client.get("/api/tts")
        agent_response = client.get("/api/agent")
        agent_summary_before_response = client.get("/api/agent/summary")
        agent_mode_response = client.post("/api/agent/mode", json={"mode": "assistant"})
        agent_settings_response = client.post(
            "/api/agent/settings",
            json={
                "aggressiveness": 65,
                "direct_answer_cooldown_ms": 9000,
                "proactive_min_silence_ms": 1500,
            },
        )
        agent_begin_response = client.post(
            "/api/agent/meeting/begin",
            json={"meeting_id": "test-meeting", "meeting_url": "https://meet.google.com/test"},
        )
        agent_end_response = client.post("/api/agent/meeting/end", json={"reason": "test"})
        agent_summary_response = client.get("/api/agent/summary")
        agent_summary_markdown_response = client.get("/api/agent/summary.md")
        agent_apply_missing_response = client.post(
            "/api/agent/candidates/apply",
            json={"candidate_id": "missing"},
        )
        tts_speak_response = client.post("/api/tts/speak", json={"text": "hello from test"})
        tts_interrupt_response = client.post("/api/tts/interrupt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["audio_consumer"]["running"] is True
    assert consumer_response.status_code == 200
    consumer_payload = consumer_response.json()
    assert consumer_payload["stats"]["running"] is True
    assert isinstance(consumer_payload["recent_endpoint_events"], list)
    assert payload["stt_worker"]["enabled"] is False
    assert stt_response.status_code == 200
    stt_payload = stt_response.json()
    assert stt_payload["stats"]["enabled"] is False
    assert stt_payload["stats"]["diarization_provider"]
    assert isinstance(stt_payload["recent_transcripts"], list)
    assert stt_label_response.status_code == 200
    assert stt_label_response.json()["label"] == "Avery"
    assert payload["tts_worker"]["enabled"] is False
    assert payload["agent"]["name"] == "Erica"
    assert isinstance(payload["agent"]["action_items"], list)
    assert isinstance(payload["agent"]["risks"], list)
    assert isinstance(payload["agent"]["parked_topics"], list)
    assert isinstance(payload["agent"]["context_summaries"], list)
    assert isinstance(payload["agent"]["reasoning_traces"], list)
    assert payload["agent"]["current_topic"] is None
    assert tts_response.status_code == 200
    tts_payload = tts_response.json()
    assert tts_payload["stats"]["enabled"] is False
    assert isinstance(tts_payload["recent_speeches"], list)
    assert agent_response.status_code == 200
    assert agent_response.json()["status"]["mode"] == "passive"
    assert agent_summary_before_response.status_code == 404
    assert agent_mode_response.status_code == 200
    assert agent_mode_response.json()["status"]["mode"] == "assistant"
    assert agent_settings_response.status_code == 200
    assert agent_settings_response.json()["status"]["settings"]["aggressiveness"] == 65
    assert agent_settings_response.json()["status"]["settings"]["direct_answer_cooldown_ms"] == 9000
    assert agent_settings_response.json()["status"]["settings"]["proactive_min_silence_ms"] == 1500
    assert agent_begin_response.status_code == 200
    assert agent_begin_response.json()["status"]["lifecycle_state"] == "in_meeting"
    assert agent_end_response.status_code == 200
    assert agent_end_response.json()["status"]["lifecycle_state"] == "meeting_ended"
    assert agent_end_response.json()["status"]["latest_summary"] is not None
    assert agent_summary_response.status_code == 200
    assert agent_summary_response.json()["summary"]["meeting_id"] == "test-meeting"
    assert agent_summary_response.json()["summary"]["json_path"]
    assert agent_summary_response.json()["summary"]["markdown_path"]
    assert isinstance(agent_summary_response.json()["summary"]["action_items"], list)
    assert isinstance(agent_summary_response.json()["summary"]["risks"], list)
    assert isinstance(agent_summary_response.json()["summary"]["parked_topics"], list)
    assert isinstance(agent_summary_response.json()["summary"]["context_summaries"], list)
    assert agent_summary_markdown_response.status_code == 200
    assert "# Erica Meeting Summary" in agent_summary_markdown_response.text
    assert agent_apply_missing_response.status_code == 404
    assert tts_speak_response.status_code == 409
    assert tts_interrupt_response.status_code == 200
    assert tts_interrupt_response.json()["interrupted"] is False
    backend_main.agent.reset()


async def test_agent_transcript_endpoint_injects_manual_utterance() -> None:
    backend_main.agent.reset()
    response = await backend_main.inject_agent_transcript(
        AgentInjectTranscriptRequest(
            text="We need users to approve invoices before payment.",
            speaker="ManualSpeaker",
            session_id="manual-session",
            utterance_id="manual-u1",
            start_ms=1000,
            end_ms=1800,
        )
    )

    payload = response.status.model_dump(mode="json")
    assert payload["lifecycle_state"] == "in_meeting"
    assert payload["meeting_id"] == "manual-session"
    assert payload["meeting_url"] == "manual://agent-transcript"
    assert payload["recent_utterances"][0]["utterance_id"] == "manual-u1"
    assert payload["recent_utterances"][0]["speaker"] == "ManualSpeaker"
    assert payload["recent_utterances"][0]["text"] == (
        "We need users to approve invoices before payment."
    )
    assert payload["requirements"][0]["text"] == (
        "We need users to approve invoices before payment."
    )
    backend_main.agent.reset()


async def test_agent_transcript_endpoint_rejects_negative_duration() -> None:
    backend_main.agent.reset()
    with pytest.raises(HTTPException) as exc_info:
        await backend_main.inject_agent_transcript(
            AgentInjectTranscriptRequest(text="hello", start_ms=2000, end_ms=1000)
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "end_ms must be greater than or equal to start_ms"
    backend_main.agent.reset()


def test_speech_start_endpoint_interrupts_tts(monkeypatch: MonkeyPatch) -> None:
    fake_tts = _FakeTts()
    fake_live_stt = _FakeLiveStt()
    fake_agent = _FakeAgent()
    monkeypatch.setattr(backend_main, "tts", fake_tts)
    monkeypatch.setattr(backend_main, "live_stt", fake_live_stt)
    monkeypatch.setattr(backend_main, "agent", fake_agent)

    event = EndpointEvent(
        type="speech_start",
        session_id="session-1",
        segment=None,
        sequence=4,
        event_ms=123.0,
    )
    backend_main._handle_endpoint_event(event)

    assert fake_live_stt.events == [event]
    assert fake_agent.speech_starts == [123.0]
    assert fake_tts.interrupt_reasons == ["human_speech"]


def test_speech_end_endpoint_notifies_agent_silence(monkeypatch: MonkeyPatch) -> None:
    fake_tts = _FakeTts()
    fake_live_stt = _FakeLiveStt()
    fake_agent = _FakeAgent()
    monkeypatch.setattr(backend_main, "tts", fake_tts)
    monkeypatch.setattr(backend_main, "live_stt", fake_live_stt)
    monkeypatch.setattr(backend_main, "agent", fake_agent)

    event = EndpointEvent(
        type="speech_end",
        session_id="session-1",
        segment=None,
        sequence=5,
        event_ms=456.0,
    )
    backend_main._handle_endpoint_event(event)

    assert fake_live_stt.events == [event]
    assert fake_agent.silences == [(456.0, fake_tts)]
    assert fake_tts.interrupt_reasons == []


class _FakeTts:
    def __init__(self) -> None:
        self.interrupt_reasons: list[str] = []

    def interrupt_current(self, reason: str) -> bool:
        self.interrupt_reasons.append(reason)
        return True

    def stats(self) -> SimpleNamespace:
        return SimpleNamespace(
            enabled=True,
            running=True,
            last_error=None,
        )


class _FakeLiveStt:
    def __init__(self) -> None:
        self.events: list[EndpointEvent] = []

    def handle_endpoint(self, event: EndpointEvent) -> None:
        self.events.append(event)

    def stats(self) -> SimpleNamespace:
        return SimpleNamespace(
            enabled=True,
            running=True,
            last_error=None,
        )


class _FakeAgent:
    def __init__(self) -> None:
        self.speech_starts: list[float] = []
        self.silences: list[tuple[float, _FakeTts]] = []
        self.readiness: object | None = None

    def observe_human_speech_start(self, event_ms: float) -> None:
        self.speech_starts.append(event_ms)

    def observe_silence(self, event_ms: float, *, speaker: _FakeTts) -> None:
        self.silences.append((event_ms, speaker))

    def set_readiness(self, readiness: object) -> object:
        self.readiness = readiness
        return readiness
