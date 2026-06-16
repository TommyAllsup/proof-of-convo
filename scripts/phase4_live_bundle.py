from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from scripts.capture_phase4_snapshot import capture_snapshot
from scripts.phase4_live_report import (
    LiveValidationResult,
    infer_checks_from_artifacts,
    render_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture Phase 4 live runtime artifacts and write the validation report."
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path(".data/phase4-live"))
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument("--meeting-url", default="unrecorded")
    parser.add_argument("--tester", default="unrecorded")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--preflight-json",
        default=".data/test-phase4-preflight/phase-4-preflight.json",
    )
    parser.add_argument("--capture-active", action="store_true")
    parser.add_argument("--transcript-visible", action="store_true")
    parser.add_argument("--direct-answer-audible", action="store_true")
    parser.add_argument("--facilitator-auto-speak-observed", action="store_true")
    parser.add_argument("--summary-generated", action="store_true")
    parser.add_argument("--provider-telemetry-visible", action="store_true")
    parser.add_argument("--no-feedback-loop", action="store_true")
    parser.add_argument("--median-response-latency-ms", type=float, default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if snapshot capture fails or the final report does not pass.",
    )
    args = parser.parse_args()

    report = capture_and_report(
        backend_url=args.backend_url,
        output_dir=args.output_dir,
        timeout_s=args.timeout_s,
        meeting_url=args.meeting_url,
        tester=args.tester,
        output=args.output,
        json_output=args.json_output,
        preflight_json=args.preflight_json,
        capture_active=args.capture_active,
        transcript_visible=args.transcript_visible,
        direct_answer_audible=args.direct_answer_audible,
        facilitator_auto_speak_observed=args.facilitator_auto_speak_observed,
        summary_generated=args.summary_generated,
        provider_telemetry_visible=args.provider_telemetry_visible,
        no_feedback_loop=args.no_feedback_loop,
        median_response_latency_ms=args.median_response_latency_ms,
        notes=args.notes,
    )
    print(f"snapshot_ok={report['snapshot_ok']}")
    print(f"passed={report['passed']}")
    print(f"markdown={report['markdown_path']}")
    print(f"json={report['json_path']}")
    if args.strict and (not report["snapshot_ok"] or not report["passed"]):
        raise SystemExit(1)


def capture_and_report(
    *,
    backend_url: str,
    output_dir: Path,
    timeout_s: float = 3.0,
    meeting_url: str = "unrecorded",
    tester: str = "unrecorded",
    output: Path | None = None,
    json_output: Path | None = None,
    preflight_json: str | None = None,
    capture_active: bool = False,
    transcript_visible: bool = False,
    direct_answer_audible: bool = False,
    facilitator_auto_speak_observed: bool = False,
    summary_generated: bool = False,
    provider_telemetry_visible: bool = False,
    no_feedback_loop: bool = False,
    median_response_latency_ms: float | None = None,
    notes: str = "",
) -> dict[str, object]:
    snapshot = capture_snapshot(
        backend_url=backend_url,
        output_dir=output_dir,
        timeout_s=timeout_s,
    )
    paths = _snapshot_paths(output_dir)
    inferred = infer_checks_from_artifacts(
        preflight_json=preflight_json,
        health_json=str(paths["health"]),
        sessions_json=str(paths["sessions"]),
        audio_consumer_json=str(paths["audio_consumer"]),
        agent_status_json=str(paths["agent_status"]),
        stt_status_json=str(paths["stt_status"]),
        agent_summary_json=str(paths["agent_summary"]),
        tts_status_json=str(paths["tts_status"]),
    )
    report = LiveValidationResult(
        meeting_url=meeting_url,
        tester=tester,
        capture_active=capture_active or inferred.get("capture_active", False),
        transcript_visible=transcript_visible or inferred.get("transcript_visible", False),
        direct_answer_audible=direct_answer_audible
        or inferred.get("direct_answer_audible", False),
        facilitator_auto_speak_observed=facilitator_auto_speak_observed
        or inferred.get("facilitator_auto_speak_observed", False),
        summary_generated=summary_generated or inferred.get("summary_generated", False),
        provider_telemetry_visible=provider_telemetry_visible
        or inferred.get("provider_telemetry_visible", False),
        no_feedback_loop=no_feedback_loop or inferred.get("no_feedback_loop", False),
        median_response_latency_ms=median_response_latency_ms,
        notes=notes,
        preflight_json=preflight_json,
        health_json=str(paths["health"]),
        sessions_json=str(paths["sessions"]),
        audio_consumer_json=str(paths["audio_consumer"]),
        agent_status_json=str(paths["agent_status"]),
        stt_status_json=str(paths["stt_status"]),
        agent_summary_json=str(paths["agent_summary"]),
        tts_status_json=str(paths["tts_status"]),
        inferred_checks=inferred,
        created_at=snapshot.created_at,
    )
    markdown_path = output or _default_markdown_path(report.created_at)
    json_path = json_output or markdown_path.with_suffix(".json")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "snapshot_ok": snapshot.ok,
                "snapshot_manifest": str(output_dir / "phase4-snapshot-manifest.json"),
                "passed": report.passed,
                **asdict(report),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "snapshot_ok": snapshot.ok,
        "passed": report.passed,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "snapshot_manifest": str(output_dir / "phase4-snapshot-manifest.json"),
    }


def _snapshot_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "health": output_dir / "health.json",
        "sessions": output_dir / "sessions.json",
        "audio_consumer": output_dir / "audio_consumer.json",
        "agent_status": output_dir / "agent_status.json",
        "stt_status": output_dir / "stt_status.json",
        "tts_status": output_dir / "tts_status.json",
        "agent_summary": output_dir / "agent_summary.json",
    }


def _default_markdown_path(created_at: str) -> Path:
    date = created_at[:10]
    return Path("docs/benchmarks") / f"phase-4-live-google-meet-validation-{date}.md"


if __name__ == "__main__":
    main()
