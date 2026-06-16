from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class LiveValidationResult:
    meeting_url: str
    tester: str
    capture_active: bool
    transcript_visible: bool
    direct_answer_audible: bool
    facilitator_auto_speak_observed: bool
    summary_generated: bool
    provider_telemetry_visible: bool
    no_feedback_loop: bool
    median_response_latency_ms: float | None
    notes: str
    preflight_json: str | None
    health_json: str | None
    sessions_json: str | None
    audio_consumer_json: str | None
    agent_status_json: str | None
    stt_status_json: str | None
    agent_summary_json: str | None
    tts_status_json: str | None
    inferred_checks: dict[str, bool]
    created_at: str

    @property
    def passed(self) -> bool:
        return all(
            [
                self.capture_active,
                self.transcript_visible,
                self.direct_answer_audible,
                self.facilitator_auto_speak_observed,
                self.summary_generated,
                self.provider_telemetry_visible,
                self.no_feedback_loop,
            ]
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Phase 4 live Google Meet validation evidence report."
    )
    parser.add_argument("--meeting-url", default="unrecorded")
    parser.add_argument("--tester", default="unrecorded")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--capture-active", action="store_true")
    parser.add_argument("--transcript-visible", action="store_true")
    parser.add_argument("--direct-answer-audible", action="store_true")
    parser.add_argument("--facilitator-auto-speak-observed", action="store_true")
    parser.add_argument("--summary-generated", action="store_true")
    parser.add_argument("--provider-telemetry-visible", action="store_true")
    parser.add_argument("--no-feedback-loop", action="store_true")
    parser.add_argument("--median-response-latency-ms", type=float, default=None)
    parser.add_argument("--preflight-json", default=None)
    parser.add_argument("--health-json", default=None)
    parser.add_argument("--sessions-json", default=None)
    parser.add_argument("--audio-consumer-json", default=None)
    parser.add_argument("--agent-status-json", default=None)
    parser.add_argument("--stt-status-json", default=None)
    parser.add_argument("--agent-summary-json", default=None)
    parser.add_argument("--tts-status-json", default=None)
    parser.add_argument(
        "--infer-from-artifacts",
        action="store_true",
        help="Infer objective checks from supplied agent/STT/TTS/summary JSON artifacts.",
    )
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    inferred = (
        infer_checks_from_artifacts(
            preflight_json=args.preflight_json,
            health_json=args.health_json,
            sessions_json=args.sessions_json,
            audio_consumer_json=args.audio_consumer_json,
            agent_status_json=args.agent_status_json,
            stt_status_json=args.stt_status_json,
            agent_summary_json=args.agent_summary_json,
            tts_status_json=args.tts_status_json,
        )
        if args.infer_from_artifacts
        else {}
    )
    report = LiveValidationResult(
        meeting_url=args.meeting_url,
        tester=args.tester,
        capture_active=args.capture_active or inferred.get("capture_active", False),
        transcript_visible=args.transcript_visible or inferred.get("transcript_visible", False),
        direct_answer_audible=args.direct_answer_audible
        or inferred.get("direct_answer_audible", False),
        facilitator_auto_speak_observed=args.facilitator_auto_speak_observed
        or inferred.get("facilitator_auto_speak_observed", False),
        summary_generated=args.summary_generated or inferred.get("summary_generated", False),
        provider_telemetry_visible=args.provider_telemetry_visible
        or inferred.get("provider_telemetry_visible", False),
        no_feedback_loop=args.no_feedback_loop or inferred.get("no_feedback_loop", False),
        median_response_latency_ms=args.median_response_latency_ms,
        notes=args.notes,
        preflight_json=args.preflight_json,
        health_json=args.health_json,
        sessions_json=args.sessions_json,
        audio_consumer_json=args.audio_consumer_json,
        agent_status_json=args.agent_status_json,
        stt_status_json=args.stt_status_json,
        agent_summary_json=args.agent_summary_json,
        tts_status_json=args.tts_status_json,
        inferred_checks=inferred,
        created_at=datetime.now(UTC).isoformat(),
    )
    output = args.output or _default_markdown_path(report.created_at)
    json_output = args.json_output or output.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    json_output.write_text(
        json.dumps({"passed": report.passed, **asdict(report)}, indent=2),
        encoding="utf-8",
    )
    print(f"passed={report.passed}")
    print(f"markdown={output}")
    print(f"json={json_output}")


def render_markdown(report: LiveValidationResult) -> str:
    rows = [
        ("Meet capture active in backend", report.capture_active),
        ("Transcript visible in extension", report.transcript_visible),
        ("Direct-address answer audible in Meet", report.direct_answer_audible),
        ("Facilitator auto-speak observed after silence", report.facilitator_auto_speak_observed),
        ("Meeting summary generated", report.summary_generated),
        ("Provider telemetry visible", report.provider_telemetry_visible),
        ("No feedback loop or repeated self-interruption", report.no_feedback_loop),
    ]
    lines = [
        "# Phase 4 Live Google Meet Validation",
        "",
        f"- Created: `{report.created_at}`",
        f"- Meeting URL: {report.meeting_url}",
        f"- Tester: {report.tester}",
        f"- Passed: `{report.passed}`",
        (
            "- Median response latency: "
            + (
                f"`{report.median_response_latency_ms:.0f} ms`"
                if report.median_response_latency_ms is not None
                else "`not recorded`"
            )
        ),
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | {'PASS' if ok else 'FAIL'} |" for name, ok in rows)
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            f"- Preflight JSON: `{report.preflight_json or 'not recorded'}`",
            f"- Health JSON: `{report.health_json or 'not recorded'}`",
            f"- Sessions JSON: `{report.sessions_json or 'not recorded'}`",
            f"- Audio consumer JSON: `{report.audio_consumer_json or 'not recorded'}`",
            f"- Agent status JSON: `{report.agent_status_json or 'not recorded'}`",
            f"- STT status JSON: `{report.stt_status_json or 'not recorded'}`",
            f"- Agent summary JSON: `{report.agent_summary_json or 'not recorded'}`",
            f"- TTS status JSON: `{report.tts_status_json or 'not recorded'}`",
            "",
            "## Inferred Checks",
            "",
            "| Check | Inferred |",
            "|---|---|",
        ]
    )
    if report.inferred_checks:
        lines.extend(
            f"| {key.replace('_', ' ')} | {'PASS' if value else 'FAIL'} |"
            for key, value in sorted(report.inferred_checks.items())
        )
    else:
        lines.append("| none | not requested |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            report.notes or "None.",
            "",
        ]
    )
    return "\n".join(lines)


def infer_checks_from_artifacts(
    *,
    preflight_json: str | None = None,
    health_json: str | None = None,
    sessions_json: str | None = None,
    audio_consumer_json: str | None = None,
    agent_status_json: str | None = None,
    stt_status_json: str | None = None,
    agent_summary_json: str | None = None,
    tts_status_json: str | None = None,
) -> dict[str, bool]:
    preflight = _load_json_object(preflight_json)
    health = _load_json_object(health_json)
    sessions = _load_json_object(sessions_json)
    audio_consumer = _load_json_object(audio_consumer_json)
    agent_status = _extract_agent_status(_load_json_object(agent_status_json))
    stt_status = _load_json_object(stt_status_json)
    agent_summary = _load_json_object(agent_summary_json)
    tts_status = _load_json_object(tts_status_json)

    return {
        "capture_active": _has_active_capture(
            health=health,
            sessions=sessions,
            audio_consumer=audio_consumer,
        ),
        "transcript_visible": _has_transcripts(
            stt_status=stt_status,
            agent_status=agent_status,
        ),
        "direct_answer_audible": _has_completed_tts(tts_status),
        "facilitator_auto_speak_observed": _has_facilitator_auto_speak(
            agent_status=agent_status,
            preflight=preflight,
        ),
        "summary_generated": _has_summary(
            agent_status=agent_status,
            agent_summary=agent_summary,
        ),
        "provider_telemetry_visible": _has_provider_telemetry(
            agent_status=agent_status,
            preflight=preflight,
        ),
        "no_feedback_loop": _has_no_feedback_loop(tts_status),
    }


def _load_json_object(path: str | None) -> dict[str, object]:
    if not path:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _extract_agent_status(agent_status: dict[str, object]) -> dict[str, object]:
    nested = agent_status.get("status")
    return nested if isinstance(nested, dict) else agent_status


def _has_active_capture(
    *,
    health: dict[str, object],
    sessions: dict[str, object],
    audio_consumer: dict[str, object],
) -> bool:
    active_sessions = _int_value(health.get("active_sessions"))
    sessions_list = sessions.get("sessions")
    session_count = len(sessions_list) if isinstance(sessions_list, list) else 0
    consumer_stats = audio_consumer.get("stats")
    consumer_running = isinstance(consumer_stats, dict) and consumer_stats.get("running") is True
    return (active_sessions > 0 or session_count > 0) and consumer_running


def _has_transcripts(
    *,
    stt_status: dict[str, object],
    agent_status: dict[str, object],
) -> bool:
    recent_transcripts = stt_status.get("recent_transcripts")
    if isinstance(recent_transcripts, list) and bool(recent_transcripts):
        return True
    stats = stt_status.get("stats")
    if isinstance(stats, dict) and _positive_int(stats.get("completed_transcripts")):
        return True
    recent_utterances = agent_status.get("recent_utterances")
    return isinstance(recent_utterances, list) and bool(recent_utterances)


def _has_completed_tts(tts_status: dict[str, object]) -> bool:
    stats = tts_status.get("stats")
    if isinstance(stats, dict) and _positive_int(stats.get("completed_speeches")):
        return True
    recent_speeches = tts_status.get("recent_speeches")
    if not isinstance(recent_speeches, list):
        return False
    for item in recent_speeches:
        if (
            isinstance(item, dict)
            and item.get("error") in (None, "")
            and not item.get("interrupted")
        ):
            return True
    return False


def _has_facilitator_auto_speak(
    *,
    agent_status: dict[str, object],
    preflight: dict[str, object],
) -> bool:
    checks = preflight.get("checks")
    if isinstance(checks, list):
        for item in checks:
            if (
                isinstance(item, dict)
                and item.get("name") == "facilitator_auto_speech"
                and item.get("ok") is True
            ):
                return True

    traces = agent_status.get("reasoning_traces")
    if not isinstance(traces, list):
        return False
    for item in traces:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        candidate_type = item.get("candidate_type")
        if (
            action in {"ask_clarifying_question", "speak_now"}
            and candidate_type == "clarifying_question"
            and item.get("can_auto_speak") is True
        ):
            return True
    return False


def _has_summary(
    *,
    agent_status: dict[str, object],
    agent_summary: dict[str, object],
) -> bool:
    if agent_summary:
        return True
    summary = agent_status.get("latest_summary")
    return isinstance(summary, dict) and bool(summary)


def _has_provider_telemetry(
    *,
    agent_status: dict[str, object],
    preflight: dict[str, object],
) -> bool:
    traces = agent_status.get("llm_call_traces")
    if isinstance(traces, list) and bool(traces):
        return True
    checks = preflight.get("checks")
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("name") == "provider_telemetry"
        and item.get("ok") is True
        for item in checks
    )


def _has_no_feedback_loop(tts_status: dict[str, object]) -> bool:
    stats = tts_status.get("stats")
    if not isinstance(stats, dict):
        return False
    completed = _int_value(stats.get("completed_speeches"))
    interrupted = _int_value(stats.get("interrupted_speeches"))
    errors = _int_value(stats.get("processing_errors"))
    if completed <= 0 or errors > 0:
        return False
    return interrupted <= max(1, completed // 2)


def _positive_int(value: object) -> bool:
    return _int_value(value) > 0


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _default_markdown_path(created_at: str) -> Path:
    date = created_at[:10]
    return Path("docs/benchmarks") / f"phase-4-live-google-meet-validation-{date}.md"


if __name__ == "__main__":
    main()
