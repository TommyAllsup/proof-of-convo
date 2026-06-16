from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from scripts import capture_phase4_snapshot


def test_capture_phase4_snapshot_writes_runtime_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    responses: dict[str, dict[str, Any]] = {
        "http://backend.test/health": {"ok": True},
        "http://backend.test/api/sessions": {"sessions": [{"session_id": "s1"}]},
        "http://backend.test/api/audio/consumer": {"stats": {"running": True}},
        "http://backend.test/api/agent": {"status": {"recent_utterances": [{"text": "hi"}]}},
        "http://backend.test/api/stt": {"stats": {"completed_transcripts": 1}},
        "http://backend.test/api/tts": {"stats": {"completed_speeches": 1}},
        "http://backend.test/api/agent/summary": {"summary": {"meeting_id": "m1"}},
    }
    monkeypatch.setattr(
        capture_phase4_snapshot,
        "_urlopen",
        _fake_urlopen(responses),
    )

    snapshot = capture_phase4_snapshot.capture_snapshot(
        backend_url="http://backend.test/",
        output_dir=tmp_path,
    )

    assert snapshot.ok is True
    assert {artifact.name for artifact in snapshot.artifacts} == {
        "health",
        "sessions",
        "audio_consumer",
        "agent_status",
        "stt_status",
        "tts_status",
        "agent_summary",
    }
    assert json.loads((tmp_path / "agent_status.json").read_text(encoding="utf-8")) == {
        "status": {"recent_utterances": [{"text": "hi"}]}
    }
    manifest = json.loads((tmp_path / "phase4-snapshot-manifest.json").read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert manifest["backend_url"] == "http://backend.test"


def test_capture_phase4_snapshot_treats_missing_summary_as_optional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    responses: dict[str, dict[str, Any]] = {
        "http://backend.test/health": {"ok": True},
        "http://backend.test/api/sessions": {"sessions": []},
        "http://backend.test/api/audio/consumer": {"stats": {"running": True}},
        "http://backend.test/api/agent": {"status": {}},
        "http://backend.test/api/stt": {"stats": {}},
        "http://backend.test/api/tts": {"stats": {}},
    }
    monkeypatch.setattr(
        capture_phase4_snapshot,
        "_urlopen",
        _fake_urlopen(responses),
    )

    snapshot = capture_phase4_snapshot.capture_snapshot(
        backend_url="http://backend.test",
        output_dir=tmp_path,
    )

    assert snapshot.ok is True
    summary = json.loads((tmp_path / "agent_summary.json").read_text(encoding="utf-8"))
    assert summary["optional"] is True
    assert summary["ok"] is False


def test_capture_phase4_snapshot_fails_required_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(capture_phase4_snapshot, "_urlopen", _fake_urlopen({}))

    snapshot = capture_phase4_snapshot.capture_snapshot(
        backend_url="http://backend.test",
        output_dir=tmp_path,
    )

    assert snapshot.ok is False
    failures = [artifact for artifact in snapshot.artifacts if not artifact.ok]
    assert {artifact.name for artifact in failures} == {
        "health",
        "sessions",
        "audio_consumer",
        "agent_status",
        "stt_status",
        "tts_status",
    }


class _FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type, exc, traceback

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _fake_urlopen(responses: dict[str, dict[str, Any]]) -> object:
    def urlopen(url: str, *, timeout: float) -> _FakeResponse:
        _ = timeout
        if url not in responses:
            raise OSError(f"missing fake response for {url}")
        return _FakeResponse(responses[url])

    return urlopen
