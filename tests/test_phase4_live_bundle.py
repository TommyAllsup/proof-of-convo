from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from scripts import capture_phase4_snapshot
from scripts.phase4_live_bundle import capture_and_report


def test_phase4_live_bundle_captures_snapshots_and_writes_passing_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    responses: dict[str, dict[str, Any]] = {
        "http://backend.test/health": {"ok": True, "active_sessions": 1},
        "http://backend.test/api/sessions": {"sessions": [{"session_id": "s1"}]},
        "http://backend.test/api/audio/consumer": {"stats": {"running": True}},
        "http://backend.test/api/agent": {
            "status": {
                "recent_utterances": [{"text": "hello"}],
                "latest_summary": {"meeting_id": "meeting-1"},
                "llm_call_traces": [{"operation": "reasoning"}],
            }
        },
        "http://backend.test/api/stt": {
            "stats": {"completed_transcripts": 1},
            "recent_transcripts": [],
        },
        "http://backend.test/api/tts": {
            "stats": {
                "completed_speeches": 2,
                "interrupted_speeches": 0,
                "processing_errors": 0,
            },
            "recent_speeches": [],
        },
        "http://backend.test/api/agent/summary": {"summary": {"meeting_id": "meeting-1"}},
    }
    preflight = tmp_path / "preflight.json"
    preflight.write_text(
        json.dumps(
            {
                "checks": [
                    {"name": "facilitator_auto_speech", "ok": True},
                    {"name": "provider_telemetry", "ok": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(capture_phase4_snapshot, "_urlopen", _fake_urlopen(responses))

    result = capture_and_report(
        backend_url="http://backend.test",
        output_dir=tmp_path / "snapshots",
        output=tmp_path / "report.md",
        json_output=tmp_path / "report.json",
        preflight_json=str(preflight),
        meeting_url="https://meet.google.com/test",
        tester="tester",
    )

    assert result["snapshot_ok"] is True
    assert result["passed"] is True
    assert Path(str(result["snapshot_manifest"])).exists()
    report_json = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report_json["snapshot_ok"] is True
    assert report_json["passed"] is True
    assert report_json["health_json"] == str(tmp_path / "snapshots" / "health.json")
    assert "| Direct-address answer audible in Meet | PASS |" in (
        tmp_path / "report.md"
    ).read_text(encoding="utf-8")


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
