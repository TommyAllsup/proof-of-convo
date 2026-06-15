from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend import main as backend_main
from backend.audio.endpointing import EndpointEvent

app = backend_main.app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        consumer_response = client.get("/api/audio/consumer")
        stt_response = client.get("/api/stt")
        tts_response = client.get("/api/tts")
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
    assert isinstance(stt_payload["recent_transcripts"], list)
    assert payload["tts_worker"]["enabled"] is False
    assert tts_response.status_code == 200
    tts_payload = tts_response.json()
    assert tts_payload["stats"]["enabled"] is False
    assert isinstance(tts_payload["recent_speeches"], list)
    assert tts_speak_response.status_code == 409
    assert tts_interrupt_response.status_code == 200
    assert tts_interrupt_response.json()["interrupted"] is False


def test_speech_start_endpoint_interrupts_tts(monkeypatch: MonkeyPatch) -> None:
    fake_tts = _FakeTts()
    fake_live_stt = _FakeLiveStt()
    monkeypatch.setattr(backend_main, "tts", fake_tts)
    monkeypatch.setattr(backend_main, "live_stt", fake_live_stt)

    event = EndpointEvent(
        type="speech_start",
        session_id="session-1",
        segment=None,
        sequence=4,
        event_ms=123.0,
    )
    backend_main._handle_endpoint_event(event)

    assert fake_live_stt.events == [event]
    assert fake_tts.interrupt_reasons == ["human_speech"]


class _FakeTts:
    def __init__(self) -> None:
        self.interrupt_reasons: list[str] = []

    def interrupt_current(self, reason: str) -> bool:
        self.interrupt_reasons.append(reason)
        return True


class _FakeLiveStt:
    def __init__(self) -> None:
        self.events: list[EndpointEvent] = []

    def handle_endpoint(self, event: EndpointEvent) -> None:
        self.events.append(event)
