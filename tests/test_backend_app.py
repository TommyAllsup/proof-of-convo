from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        consumer_response = client.get("/api/audio/consumer")
        stt_response = client.get("/api/stt")

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
