from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace

from backend.agent import FakeLLMClient, MeetingAgentOrchestrator
from backend.agent.orchestrator import AgentConfig
from backend.audio.diarization import SpeakerAttribution
from backend.audio.live_stt import LiveTranscript
from backend.audio.stt import SttTranscript
from backend.audio.stt_windows import UtteranceWindow
from backend.models.agent import (
    AgentBeginMeetingRequest,
    AgentReasoningDecision,
    AgentStatus,
    RequirementRefinement,
)
from backend.models.audio import Utterance


@dataclass(frozen=True)
class EvalUtterance:
    speaker: str
    text: str


@dataclass(frozen=True)
class EvalScenario:
    scenario_id: str
    description: str
    mode: str
    utterances: list[EvalUtterance]
    expected_requirements: int = 0
    expected_open_questions: int = 0
    expected_decisions: int = 0
    expected_action_items: int = 0
    expected_risks: int = 0
    expected_parked_topics: int = 0
    expected_acceptance_criteria: int = 0
    expected_accepted_requirements: int = 0
    expected_final_mode: str | None = None
    expected_lifecycle_state: str = "in_meeting"
    expected_context_summary_contains: str | None = None
    expected_candidate_types: list[str] = field(default_factory=list)
    llm_decisions: list[AgentReasoningDecision] = field(default_factory=list)
    llm_context_summaries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    passed: bool
    score: float
    checks: dict[str, bool]
    observed: dict[str, object]


@dataclass(frozen=True)
class EvalReport:
    passed: bool
    score: float
    scenarios: list[ScenarioResult]
    artifacts: dict[str, str]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic Phase 4 agent behavior evals.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".data/agent-evals"),
        help="Directory for JSON and Markdown eval reports.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any scenario fails.",
    )
    args = parser.parse_args()

    report = run_eval(artifact_dir=args.artifact_dir)
    print(f"score={report.score:.3f} passed={report.passed}")
    print(f"json={report.artifacts['json']}")
    print(f"markdown={report.artifacts['markdown']}")
    if args.strict and not report.passed:
        raise SystemExit(1)


def run_eval(*, artifact_dir: Path) -> EvalReport:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    scenarios = default_scenarios()
    results = [run_scenario(scenario) for scenario in scenarios]
    score = sum(result.score for result in results) / len(results) if results else 1.0
    passed = all(result.passed for result in results)

    report_without_artifacts = EvalReport(
        passed=passed,
        score=score,
        scenarios=results,
        artifacts={},
    )
    json_path = artifact_dir / "phase-4-agent-eval.json"
    markdown_path = artifact_dir / "phase-4-agent-eval.md"
    json_path.write_text(
        json.dumps(_report_payload(report_without_artifacts), indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_report_markdown(report_without_artifacts), encoding="utf-8")
    return EvalReport(
        passed=passed,
        score=score,
        scenarios=results,
        artifacts={"json": str(json_path), "markdown": str(markdown_path)},
    )


def run_scenario(scenario: EvalScenario) -> ScenarioResult:
    agent = MeetingAgentOrchestrator(
        mode=scenario.mode,  # type: ignore[arg-type]
        config=AgentConfig(context_summary_utterance_interval=3),
        llm_client=(
            FakeLLMClient(
                decisions=scenario.llm_decisions,
                context_summaries=scenario.llm_context_summaries,
            )
            if scenario.llm_decisions or scenario.llm_context_summaries
            else None
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id=scenario.scenario_id))
    speaker = _EvalSpeaker()
    for index, utterance in enumerate(scenario.utterances, start=1):
        agent.observe_transcript(
            _live_transcript(
                utterance_id=f"{scenario.scenario_id}-u{index}",
                session_id=scenario.scenario_id,
                speaker=utterance.speaker,
                text=utterance.text,
                index=index,
            ),
            speaker=speaker,
        )
    status = agent.status()
    observed_candidate_types = [item.type for item in status.candidate_interventions]
    checks = {
        "requirements": len(status.requirements) == scenario.expected_requirements,
        "open_questions": len(status.open_questions) == scenario.expected_open_questions,
        "decisions": len(status.decisions) == scenario.expected_decisions,
        "action_items": len(status.action_items) == scenario.expected_action_items,
        "risks": len(status.risks) == scenario.expected_risks,
        "parked_topics": len(status.parked_topics) == scenario.expected_parked_topics,
        "acceptance_criteria": (
            sum(len(item.acceptance_criteria) for item in status.requirements)
            == scenario.expected_acceptance_criteria
        ),
        "accepted_requirements": (
            sum(1 for item in status.requirements if item.status == "accepted")
            == scenario.expected_accepted_requirements
        ),
        "final_mode": status.mode == (scenario.expected_final_mode or scenario.mode),
        "lifecycle_state": status.lifecycle_state == scenario.expected_lifecycle_state,
        "context_summary_text": (
            scenario.expected_context_summary_contains is None
            or any(
                scenario.expected_context_summary_contains.lower() in item.text.lower()
                for item in status.context_summaries
            )
        ),
        "candidate_types": observed_candidate_types == scenario.expected_candidate_types,
        "context_checkpoint": bool(status.context_summaries) == (len(scenario.utterances) >= 3),
    }
    passed_checks = sum(1 for value in checks.values() if value)
    score = passed_checks / len(checks)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        passed=all(checks.values()),
        score=score,
        checks=checks,
        observed=_observed_payload(status),
    )


def default_scenarios() -> list[EvalScenario]:
    return [
        EvalScenario(
            scenario_id="requirements_clarification",
            description="Requirement should be captured and produce one clarifying candidate.",
            mode="passive",
            utterances=[
                EvalUtterance("Speaker_1", "We need users to approve invoices before payment."),
                EvalUtterance("Speaker_2", "What is the launch date?"),
                EvalUtterance("Speaker_1", "We decided to launch Friday."),
            ],
            expected_requirements=1,
            expected_open_questions=1,
            expected_decisions=1,
            expected_candidate_types=["clarifying_question"],
        ),
        EvalScenario(
            scenario_id="fake_llm_candidate_quality",
            description="Injected LLM decision should drive candidate text and rationale.",
            mode="passive",
            utterances=[
                EvalUtterance("Speaker_1", "Users must approve invoices before payment."),
                EvalUtterance("Speaker_2", "Action item: confirm owners."),
                EvalUtterance("Speaker_1", "Risk: QA is blocked."),
            ],
            expected_requirements=1,
            expected_action_items=1,
            expected_risks=1,
            expected_candidate_types=["clarifying_question"],
            llm_decisions=[
                AgentReasoningDecision(
                    action="ask_clarifying_question",
                    candidate_type="clarifying_question",
                    text="Which user roles are allowed to approve invoices?",
                    score=0.86,
                    reason="role scope is ambiguous",
                )
            ],
        ),
        EvalScenario(
            scenario_id="parking_lot_and_dedupe",
            description="Equivalent records should merge while parked topics remain traceable.",
            mode="passive",
            utterances=[
                EvalUtterance("Speaker_1", "Parking lot: Zoom support."),
                EvalUtterance("Speaker_2", "Parked topic: Zoom support."),
                EvalUtterance("Speaker_1", "Concern: QA is blocked."),
                EvalUtterance("Speaker_2", "Risk: QA is blocked."),
            ],
            expected_risks=1,
            expected_parked_topics=1,
        ),
        EvalScenario(
            scenario_id="llm_general_actions",
            description="LLM can capture a decision and draft a summary checkpoint.",
            mode="scribe",
            utterances=[
                EvalUtterance("Speaker_1", "Okay, Google Meet first."),
                EvalUtterance("Speaker_2", "That closes the platform question."),
                EvalUtterance("Speaker_1", "Next topic is rollout."),
            ],
            expected_decisions=1,
            expected_candidate_types=["summary_checkpoint"],
            llm_decisions=[
                AgentReasoningDecision(
                    action="capture_decision",
                    text="use Google Meet first",
                    score=0.72,
                    reason="group reached consensus",
                ),
                AgentReasoningDecision(
                    action="summarize",
                    candidate_type="summary_checkpoint",
                    text="Checkpoint: platform decision captured; rollout is next.",
                    score=0.79,
                    reason="topic transition detected",
                ),
                AgentReasoningDecision(
                    action="listen",
                    score=0.0,
                    reason="new topic just started",
                ),
            ],
        ),
        EvalScenario(
            scenario_id="llm_requirement_refinement",
            description="LLM can enrich an existing requirement without creating a duplicate.",
            mode="passive",
            utterances=[
                EvalUtterance("Speaker_1", "We need users to approve invoices before payment."),
                EvalUtterance("Speaker_2", "Owner is Jane and the audit trail must be saved."),
                EvalUtterance("Speaker_1", "Done when requester sees the approver name."),
            ],
            expected_requirements=1,
            expected_acceptance_criteria=2,
            expected_accepted_requirements=1,
            llm_decisions=[
                AgentReasoningDecision(
                    action="listen",
                    score=0.0,
                    reason="base requirement captured",
                ),
                AgentReasoningDecision(
                    action="listen",
                    score=0.0,
                    reason="requirement ownership refined",
                    requirement_refinement=RequirementRefinement(
                        owner="Jane",
                        status="accepted",
                        acceptance_criteria=["audit trail is saved"],
                    ),
                ),
                AgentReasoningDecision(
                    action="listen",
                    score=0.0,
                    reason="acceptance criteria refined",
                    requirement_refinement=RequirementRefinement(
                        status="accepted",
                        acceptance_criteria=["requester sees the approver name"],
                    ),
                ),
            ],
        ),
        EvalScenario(
            scenario_id="explicit_voice_controls",
            description="Addressed commands can change modes and end a meeting without candidates.",
            mode="passive",
            utterances=[
                EvalUtterance("Speaker_1", "Erica, switch to facilitator mode."),
                EvalUtterance("Speaker_1", "We decided to launch Friday."),
                EvalUtterance("Speaker_1", "Erica, end meeting."),
            ],
            expected_decisions=1,
            expected_final_mode="facilitator",
            expected_lifecycle_state="meeting_ended",
        ),
        EvalScenario(
            scenario_id="llm_context_summary",
            description="LLM can produce a richer rolling context checkpoint.",
            mode="passive",
            utterances=[
                EvalUtterance("Speaker_1", "We need users to approve invoices before payment."),
                EvalUtterance("Speaker_2", "What is the launch date?"),
                EvalUtterance("Speaker_1", "We decided to launch Friday."),
            ],
            expected_requirements=1,
            expected_open_questions=1,
            expected_decisions=1,
            expected_candidate_types=["clarifying_question"],
            expected_context_summary_contains="invoice approvals",
            llm_context_summaries=[
                "Invoice approvals need acceptance criteria; launch timing was decided for Friday."
            ],
        ),
    ]


class _EvalSpeaker:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def enqueue(self, text: str, *, interrupt: bool = False) -> object:
        _ = interrupt
        self.spoken.append(text)
        return SimpleNamespace(job_id=f"eval-job-{len(self.spoken)}")


def _live_transcript(
    *,
    utterance_id: str,
    session_id: str,
    speaker: str,
    text: str,
    index: int,
) -> LiveTranscript:
    start_ms = float(index * 1_000)
    end_ms = start_ms + 700.0
    window = UtteranceWindow(
        window_id=utterance_id,
        session_id=session_id,
        source_wav=f"eval://{session_id}",
        sample_rate=16_000,
        vad_provider="eval",
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=700.0,
        padded_start_ms=start_ms - 100.0,
        padded_end_ms=end_ms + 100.0,
        padded_duration_ms=900.0,
        start_sequence=index,
        end_sequence=index,
        peak=0.2,
        mean_rms=0.1,
    )
    transcript = SttTranscript(
        window_id=utterance_id,
        provider="eval",
        model_id="eval",
        text=text,
        language="en",
        confidence=0.95,
        wall_time_s=0.01,
        error=None,
    )
    utterance = Utterance(
        utterance_id=utterance_id,
        session_id=session_id,
        speaker=speaker,
        start_ts=start_ms / 1000.0,
        end_ts=end_ms / 1000.0,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        is_final=True,
        confidence=0.95,
        speaker_confidence=0.8,
        stt_provider="eval",
        stt_model="eval",
        vad_provider="eval",
        raw_audio_ref=f"eval://{session_id}",
    )
    return LiveTranscript(
        window=window,
        transcript=transcript,
        speaker=SpeakerAttribution(speaker=speaker, confidence=0.8, method="eval"),
        utterance=utterance,
        completed_at_ms=end_ms + 50.0,
    )


def _observed_payload(status: AgentStatus) -> dict[str, object]:
    return {
        "requirements": len(status.requirements),
        "acceptance_criteria": sum(
            len(item.acceptance_criteria) for item in status.requirements
        ),
        "accepted_requirements": sum(
            1 for item in status.requirements if item.status == "accepted"
        ),
        "open_questions": len(status.open_questions),
        "decisions": len(status.decisions),
        "action_items": len(status.action_items),
        "risks": len(status.risks),
        "parked_topics": len(status.parked_topics),
        "linked_open_questions": sum(
            1 for item in status.open_questions if item.related_requirement_ids
        ),
        "current_topic": status.current_topic.topic if status.current_topic else None,
        "mode": status.mode,
        "lifecycle_state": status.lifecycle_state,
        "candidate_types": [item.type for item in status.candidate_interventions],
        "mode_change_suggestions": [
            item.suggested_mode
            for item in status.candidate_interventions
            if item.type == "mode_change"
        ],
        "context_summaries": len(status.context_summaries),
        "llm_call_traces": len(status.llm_call_traces),
        "llm_call_operations": [item.operation for item in status.llm_call_traces],
    }


def _report_payload(report: EvalReport) -> dict[str, object]:
    return {
        "passed": report.passed,
        "score": report.score,
        "scenarios": [
            {
                **asdict(result),
            }
            for result in report.scenarios
        ],
    }


def _report_markdown(report: EvalReport) -> str:
    lines = [
        "# Phase 4 Agent Behavior Eval",
        "",
        f"- Passed: `{report.passed}`",
        f"- Score: `{report.score:.3f}`",
        "",
        "## Scenarios",
        "",
    ]
    for result in report.scenarios:
        lines.extend(
            [
                f"### {result.scenario_id}",
                "",
                f"- Passed: `{result.passed}`",
                f"- Score: `{result.score:.3f}`",
                f"- Checks: `{json.dumps(result.checks, sort_keys=True)}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
