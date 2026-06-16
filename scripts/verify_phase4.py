from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from backend.agent import FakeLLMClient, MeetingAgentOrchestrator
from backend.agent.orchestrator import AgentConfig
from backend.audio.diarization import SpeakerAttribution
from backend.audio.live_stt import LiveTranscript
from backend.audio.manager import now_ms
from backend.audio.stt import SttTranscript
from backend.audio.stt_windows import UtteranceWindow
from backend.models.agent import AgentBeginMeetingRequest, AgentReadiness, AgentSettings
from backend.models.audio import Utterance


@dataclass(frozen=True)
class Phase4Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Phase4VerificationReport:
    passed: bool
    checks: list[Phase4Check]
    artifact_path: str | None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a local Phase 4 Erica preflight before live Meet validation."
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".data/phase4-preflight"),
        help="Directory for the JSON preflight report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any Phase 4 preflight check fails.",
    )
    args = parser.parse_args()

    report = run_verification(artifact_dir=args.artifact_dir)
    for check in report.checks:
        status = "ok" if check.ok else "fail"
        print(f"[{status}] {check.name}: {check.detail}")
    if report.artifact_path:
        print(f"json={report.artifact_path}")
    print(f"passed={report.passed}")
    if args.strict and not report.passed:
        raise SystemExit(1)


def run_verification(*, artifact_dir: Path | None = None) -> Phase4VerificationReport:
    summary_dir = artifact_dir / "summaries" if artifact_dir is not None else None
    agent = MeetingAgentOrchestrator(
        mode="assistant",
        config=AgentConfig(
            direct_answer_cooldown_ms=0.0,
            proactive_min_silence_ms=500.0,
            proactive_min_aggressiveness=60,
            context_summary_utterance_interval=3,
        ),
        llm_client=FakeLLMClient(
            direct_answers=["Use Google Meet first; keep Zoom as a follow-up."],
            context_summaries=[
                "Platform choice is settled on Google Meet; invoice approval needs criteria."
            ],
        ),
        summary_dir=summary_dir,
    )
    agent.set_settings(
        AgentSettings(
            aggressiveness=90,
            direct_answer_cooldown_ms=0.0,
            proactive_min_silence_ms=500.0,
        )
    )
    agent.set_readiness(AgentReadiness(can_auto_speak=True))
    speaker = _VerifierSpeaker()

    agent.begin_meeting(
        AgentBeginMeetingRequest(
            meeting_id="phase4-preflight",
            meeting_url="local://phase4-preflight",
        )
    )
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We decided to use Google Meet first."),
        speaker=speaker,
    )
    agent.observe_transcript(
        _live_transcript("u2", "Speaker_1", "Erica, what should we use?"),
        speaker=speaker,
    )
    direct_status = agent.status()
    first_job = direct_status.active_speech_job_id
    if first_job is not None:
        agent.observe_speech_result(
            job_id=first_job,
            completed_at_ms=now_ms(),
            error=None,
            interrupted=False,
        )

    agent.observe_transcript(
        _live_transcript("u3", "Speaker_1", "Erica, switch to facilitator mode."),
        speaker=speaker,
    )
    agent.observe_transcript(
        _live_transcript("u4", "Speaker_2", "We need users to approve invoices before payment."),
        speaker=speaker,
    )
    waiting_status = agent.status()
    agent.observe_silence(6_000.0, speaker=speaker)
    auto_status = agent.status()
    second_job = auto_status.active_speech_job_id
    if second_job is not None:
        agent.observe_speech_result(
            job_id=second_job,
            completed_at_ms=now_ms(),
            error=None,
            interrupted=False,
        )

    agent.observe_transcript(_live_transcript("u5", "Speaker_2", "Action item: confirm owners."))
    agent.observe_transcript(_live_transcript("u6", "Speaker_3", "Risk: QA is blocked."))
    agent.observe_transcript(_live_transcript("u7", "Speaker_1", "Erica, end meeting."))
    final_status = agent.status()

    checks = [
        Phase4Check(
            name="direct_address_speech",
            ok=bool(speaker.spoken)
            and speaker.spoken[0] == "Use Google Meet first; keep Zoom as a follow-up.",
            detail=f"{len(speaker.spoken)} speech job(s) queued",
        ),
        Phase4Check(
            name="mode_voice_command",
            ok=waiting_status.mode == "facilitator",
            detail=f"mode={waiting_status.mode}",
        ),
        Phase4Check(
            name="facilitator_waits_for_turn",
            ok=waiting_status.runtime_state == "waiting_for_turn",
            detail=f"runtime={waiting_status.runtime_state}",
        ),
        Phase4Check(
            name="facilitator_auto_speech",
            ok=len(speaker.spoken) >= 2
            and "acceptance criteria" in speaker.spoken[1].lower(),
            detail=f"spoken={speaker.spoken[1:] if len(speaker.spoken) > 1 else []}",
        ),
        Phase4Check(
            name="structured_memory",
            ok=bool(final_status.requirements)
            and bool(final_status.decisions)
            and bool(final_status.action_items)
            and bool(final_status.risks),
            detail=(
                f"requirements={len(final_status.requirements)} "
                f"decisions={len(final_status.decisions)} "
                f"actions={len(final_status.action_items)} risks={len(final_status.risks)}"
            ),
        ),
        Phase4Check(
            name="context_summary",
            ok=any("Platform choice" in item.text for item in final_status.context_summaries),
            detail=f"context_summaries={len(final_status.context_summaries)}",
        ),
        Phase4Check(
            name="provider_telemetry",
            ok={"direct_answer", "context_summary", "reasoning"}.issubset(
                {trace.operation for trace in final_status.llm_call_traces}
            ),
            detail="operations="
            + ",".join(sorted({trace.operation for trace in final_status.llm_call_traces})),
        ),
        Phase4Check(
            name="meeting_summary",
            ok=final_status.lifecycle_state == "meeting_ended"
            and final_status.latest_summary is not None
            and final_status.latest_summary.markdown_path is not None,
            detail=f"lifecycle={final_status.lifecycle_state}",
        ),
    ]
    passed = all(check.ok for check in checks)
    artifact_path: str | None = None
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        report_path = artifact_dir / "phase-4-preflight.json"
        report_path.write_text(
            json.dumps(
                {
                    "passed": passed,
                    "checks": [asdict(check) for check in checks],
                    "spoken": speaker.spoken,
                    "latest_summary": (
                        final_status.latest_summary.model_dump(mode="json")
                        if final_status.latest_summary is not None
                        else None
                    ),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        artifact_path = str(report_path)
    return Phase4VerificationReport(passed=passed, checks=checks, artifact_path=artifact_path)


class _VerifierSpeaker:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def enqueue(self, text: str, *, interrupt: bool = False) -> object:
        _ = interrupt
        self.spoken.append(text)
        return SimpleNamespace(job_id=f"phase4-job-{len(self.spoken)}")


def _live_transcript(utterance_id: str, speaker: str, text: str) -> LiveTranscript:
    index = int(utterance_id.removeprefix("u"))
    start_ms = float(index * 1_000)
    end_ms = start_ms + 700.0
    window = UtteranceWindow(
        window_id=utterance_id,
        session_id="phase4-preflight",
        source_wav="live://phase4-preflight",
        sample_rate=16_000,
        vad_provider="rms",
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=700.0,
        padded_start_ms=start_ms - 100.0,
        padded_end_ms=end_ms + 100.0,
        padded_duration_ms=900.0,
        start_sequence=index,
        end_sequence=index + 2,
        peak=0.5,
        mean_rms=0.2,
    )
    transcript = SttTranscript(
        window_id=utterance_id,
        provider="phase4-preflight",
        model_id="fake",
        text=text,
        language="en",
        confidence=0.9,
        wall_time_s=0.01,
        error=None,
    )
    utterance = Utterance(
        utterance_id=utterance_id,
        session_id="phase4-preflight",
        speaker=speaker,
        start_ts=start_ms / 1000,
        end_ts=end_ms / 1000,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        is_final=True,
        confidence=0.9,
        speaker_confidence=0.9,
        stt_provider="phase4-preflight",
        stt_model="fake",
        vad_provider="rms",
        raw_audio_ref="live://phase4-preflight",
    )
    return LiveTranscript(
        window=window,
        transcript=transcript,
        speaker=SpeakerAttribution(speaker=speaker, confidence=0.9, method="phase4-preflight"),
        utterance=utterance,
        completed_at_ms=end_ms + 50.0,
    )


if __name__ == "__main__":
    main()
