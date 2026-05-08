from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        consumer_response = client.get("/api/audio/consumer")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["audio_consumer"]["running"] is True
    assert consumer_response.status_code == 200
    consumer_payload = consumer_response.json()
    assert consumer_payload["stats"]["running"] is True
    assert isinstance(consumer_payload["recent_endpoint_events"], list)
