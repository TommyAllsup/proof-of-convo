import json
from pathlib import Path

from scripts.phase4_live_report import (
    LiveValidationResult,
    infer_checks_from_artifacts,
    render_markdown,
)


def test_phase4_live_report_marks_passed_when_all_acceptance_checks_pass() -> None:
    report = LiveValidationResult(
        meeting_url="https://meet.google.com/test",
        tester="tester",
        capture_active=True,
        transcript_visible=True,
        direct_answer_audible=True,
        facilitator_auto_speak_observed=True,
        summary_generated=True,
        provider_telemetry_visible=True,
        no_feedback_loop=True,
        median_response_latency_ms=1450.0,
        notes="No echo observed.",
        preflight_json=".data/test-phase4-preflight/phase-4-preflight.json",
        health_json=".data/health.json",
        sessions_json=".data/sessions.json",
        audio_consumer_json=".data/audio-consumer.json",
        agent_status_json=".data/agent-status.json",
        stt_status_json=".data/stt-status.json",
        agent_summary_json=".data/agent/summary.json",
        tts_status_json=".data/tts-status.json",
        inferred_checks={"transcript_visible": True},
        created_at="2026-06-15T20:00:00+00:00",
    )

    markdown = render_markdown(report)

    assert report.passed is True
    assert "- Passed: `True`" in markdown
    assert "| Meet capture active in backend | PASS |" in markdown
    assert "| Direct-address answer audible in Meet | PASS |" in markdown
    assert "`1450 ms`" in markdown
    assert "- Agent status JSON: `.data/agent-status.json`" in markdown
    assert "| transcript visible | PASS |" in markdown
    assert "No echo observed." in markdown


def test_phase4_live_report_marks_failed_when_any_acceptance_check_fails() -> None:
    report = LiveValidationResult(
        meeting_url="https://meet.google.com/test",
        tester="tester",
        capture_active=True,
        transcript_visible=True,
        direct_answer_audible=False,
        facilitator_auto_speak_observed=True,
        summary_generated=True,
        provider_telemetry_visible=True,
        no_feedback_loop=True,
        median_response_latency_ms=None,
        notes="Audio was not heard.",
        preflight_json=None,
        health_json=None,
        sessions_json=None,
        audio_consumer_json=None,
        agent_status_json=None,
        stt_status_json=None,
        agent_summary_json=None,
        tts_status_json=None,
        inferred_checks={},
        created_at="2026-06-15T20:00:00+00:00",
    )

    markdown = render_markdown(report)

    assert report.passed is False
    assert "| Direct-address answer audible in Meet | FAIL |" in markdown
    assert "`not recorded`" in markdown
    assert "| none | not requested |" in markdown


def test_phase4_live_report_infers_checks_from_runtime_artifacts(tmp_path: Path) -> None:
    preflight_path = tmp_path / "preflight.json"
    health_path = tmp_path / "health.json"
    sessions_path = tmp_path / "sessions.json"
    consumer_path = tmp_path / "consumer.json"
    agent_path = tmp_path / "agent.json"
    stt_path = tmp_path / "stt.json"
    summary_path = tmp_path / "summary.json"
    tts_path = tmp_path / "tts.json"
    preflight_path.write_text(
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
    health_path.write_text(json.dumps({"active_sessions": 1}), encoding="utf-8")
    sessions_path.write_text(json.dumps({"sessions": [{"session_id": "s1"}]}), encoding="utf-8")
    consumer_path.write_text(json.dumps({"stats": {"running": True}}), encoding="utf-8")
    agent_path.write_text(
        json.dumps(
            {
                "status": {
                    "recent_utterances": [{"text": "hello"}],
                    "latest_summary": {"meeting_id": "meeting-1"},
                    "llm_call_traces": [{"operation": "reasoning"}],
                }
            }
        ),
        encoding="utf-8",
    )
    stt_path.write_text(
        json.dumps({"stats": {"completed_transcripts": 1}, "recent_transcripts": []}),
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps({"meeting_id": "meeting-1"}), encoding="utf-8")
    tts_path.write_text(
        json.dumps(
            {
                "stats": {
                    "completed_speeches": 2,
                    "interrupted_speeches": 0,
                    "processing_errors": 0,
                },
                "recent_speeches": [],
            }
        ),
        encoding="utf-8",
    )

    checks = infer_checks_from_artifacts(
        preflight_json=str(preflight_path),
        health_json=str(health_path),
        sessions_json=str(sessions_path),
        audio_consumer_json=str(consumer_path),
        agent_status_json=str(agent_path),
        stt_status_json=str(stt_path),
        agent_summary_json=str(summary_path),
        tts_status_json=str(tts_path),
    )

    assert checks == {
        "capture_active": True,
        "transcript_visible": True,
        "direct_answer_audible": True,
        "facilitator_auto_speak_observed": True,
        "summary_generated": True,
        "provider_telemetry_visible": True,
        "no_feedback_loop": True,
    }


def test_phase4_live_report_inference_fails_closed_for_missing_artifacts() -> None:
    checks = infer_checks_from_artifacts(
        preflight_json="/missing/preflight.json",
        health_json="/missing/health.json",
        sessions_json="/missing/sessions.json",
        audio_consumer_json="/missing/audio-consumer.json",
        agent_status_json="/missing/agent.json",
        stt_status_json="/missing/stt.json",
        agent_summary_json="/missing/summary.json",
        tts_status_json="/missing/tts.json",
    )

    assert checks == {
        "capture_active": False,
        "transcript_visible": False,
        "direct_answer_audible": False,
        "facilitator_auto_speak_observed": False,
        "summary_generated": False,
        "provider_telemetry_visible": False,
        "no_feedback_loop": False,
    }
