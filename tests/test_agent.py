from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from backend.agent import MeetingAgentOrchestrator
from backend.agent.orchestrator import AgentConfig
from backend.agent.reasoner import (
    ContextSummaryRequest,
    DirectAnswerContext,
    FakeLLMClient,
    ReasoningContext,
)
from backend.audio.diarization import SpeakerAttribution
from backend.audio.live_stt import LiveTranscript
from backend.audio.manager import now_ms
from backend.audio.stt import SttTranscript
from backend.audio.stt_windows import UtteranceWindow
from backend.models.agent import (
    AgentBeginMeetingRequest,
    AgentReadiness,
    AgentReasoningDecision,
    AgentSettings,
    RequirementRefinement,
)
from backend.models.audio import Utterance


def test_agent_begin_meeting_tracks_transcript_and_direct_candidate() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")

    status = agent.begin_meeting(
        AgentBeginMeetingRequest(meeting_id="meeting-1", meeting_url="https://meet.google.com/a")
    )
    assert status.lifecycle_state == "in_meeting"

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Hey Erica, what is in scope?"))

    status = agent.status()
    assert status.mode == "passive"
    assert status.runtime_state == "candidate_intervention"
    assert status.recent_utterances[0].text == "Hey Erica, what is in scope?"
    assert status.participants[0].speaker == "Speaker_1"
    assert status.candidate_interventions[0].type == "direct_answer"
    assert status.candidate_interventions[0].speak_allowed is False


def test_agent_assistant_mode_speaks_direct_question() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(
        mode="assistant",
        config=AgentConfig(direct_answer_cooldown_ms=0.0),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "Can Erica answer this?"),
        speaker=speaker,
    )

    status = agent.status()
    assert status.runtime_state == "speaking"
    assert status.candidate_interventions[0].speak_allowed is True
    assert speaker.spoken
    assert "not have enough meeting context" in speaker.spoken[0]
    assert status.active_speech_job_id == "job-1"


def test_agent_direct_answer_uses_meeting_memory() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )
    agent.observe_transcript(
        _live_transcript("u2", "Speaker_2", "We decided to launch on Friday.")
    )

    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "Erica, what do you have?"))

    candidate = agent.status().candidate_interventions[-1]
    assert candidate.type == "direct_answer"
    assert "latest decision is launch on friday" in candidate.text
    assert "latest requirement is: We need users" in candidate.text


def test_agent_direct_answer_uses_llm_when_available() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(direct_answers=["Use Google Meet first; Zoom stays follow-up."]),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We decided to use Google Meet first.")
    )

    agent.observe_transcript(_live_transcript("u2", "Speaker_1", "Erica, what should we use?"))

    status = agent.status()
    candidate = status.candidate_interventions[-1]
    assert candidate.type == "direct_answer"
    assert candidate.text == "Use Google Meet first; Zoom stays follow-up."
    assert status.last_error is None
    assert status.llm_call_traces[-1].operation == "direct_answer"
    assert status.llm_call_traces[-1].provider == "FakeLLMClient"
    assert status.llm_call_traces[-1].success is True
    assert status.llm_call_traces[-1].output_preview == (
        "Use Google Meet first; Zoom stays follow-up."
    )


def test_agent_direct_answer_falls_back_when_llm_answer_fails() -> None:
    agent = MeetingAgentOrchestrator(mode="passive", llm_client=_FailingDirectAnswerLLMClient())
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We decided to use Google Meet first.")
    )

    agent.observe_transcript(_live_transcript("u2", "Speaker_1", "Erica, what should we use?"))

    status = agent.status()
    candidate = status.candidate_interventions[-1]
    assert candidate.type == "direct_answer"
    assert "latest decision is use google meet first" in candidate.text
    assert status.last_error == "direct answer failed: TimeoutError: timed out"
    assert status.llm_call_traces[-1].operation == "direct_answer"
    assert status.llm_call_traces[-1].success is False
    assert status.llm_call_traces[-1].error == "TimeoutError: timed out"


def test_agent_explicit_voice_command_switches_mode_without_candidate() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "Erica, switch to facilitator mode.")
    )

    status = agent.status()
    assert status.mode == "facilitator"
    assert status.runtime_state == "manual_override"
    assert status.candidate_interventions == []
    assert status.recent_utterances[0].text == "Erica, switch to facilitator mode."


def test_agent_explicit_voice_command_can_turn_agent_off_and_clear_candidates() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Hey Erica, what is in scope?"))
    assert agent.status().candidate_interventions

    agent.observe_transcript(_live_transcript("u2", "Speaker_1", "Erica, switch to off mode."))

    status = agent.status()
    assert status.mode == "off"
    assert status.runtime_state == "manual_override"
    assert status.candidate_interventions == []


def test_agent_explicit_voice_command_ends_meeting_with_summary(tmp_path: Path) -> None:
    agent = MeetingAgentOrchestrator(mode="assistant", summary_dir=tmp_path)
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "We decided to launch Friday."))

    agent.observe_transcript(_live_transcript("u2", "Speaker_1", "Erica, end meeting."))

    status = agent.status()
    assert status.lifecycle_state == "meeting_ended"
    assert status.runtime_state == "manual_override"
    assert status.latest_summary is not None
    assert status.latest_summary.decisions[0].text == "launch friday"
    assert status.latest_summary.markdown_path is not None
    assert Path(status.latest_summary.markdown_path).exists()
    assert status.candidate_interventions == []


def test_agent_speech_result_moves_speaking_to_cooldown() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(
        mode="assistant",
        config=AgentConfig(direct_answer_cooldown_ms=60_000.0),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "Hey Erica, are we on track?"),
        speaker=speaker,
    )
    assert agent.status().runtime_state == "speaking"

    agent.observe_speech_result(
        job_id="job-1",
        completed_at_ms=now_ms(),
        error=None,
        interrupted=False,
    )

    status = agent.status()
    assert status.runtime_state == "cooldown"
    assert status.active_speech_job_id is None
    assert status.last_speech_job_id == "job-1"
    assert status.last_agent_speech_at_ms is not None


def test_agent_status_moves_from_cooldown_to_idle_after_cooldown_expires() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(
        mode="assistant",
        config=AgentConfig(direct_answer_cooldown_ms=0.0),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "Hey Erica, are we on track?"),
        speaker=speaker,
    )
    agent.observe_speech_result(
        job_id="job-1",
        completed_at_ms=2_500.0,
        error=None,
        interrupted=False,
    )

    status = agent.status()

    assert status.runtime_state == "idle_listening"
    assert status.last_agent_speech_at_ms == 2_500.0


def test_agent_speech_error_records_error_and_leaves_candidate_visible() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(mode="assistant")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "Can Erica help?"),
        speaker=speaker,
    )

    agent.observe_speech_result(
        job_id="job-1",
        completed_at_ms=2_500.0,
        error="provider failed",
        interrupted=False,
    )

    status = agent.status()
    assert status.runtime_state == "candidate_intervention"
    assert status.last_error == "provider failed"
    assert status.candidate_interventions


def test_agent_can_update_settings_and_dismiss_candidate() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Hey Erica, are you there?"))
    candidate_id = agent.status().candidate_interventions[0].candidate_id

    settings = agent.status().settings.model_copy(update={"aggressiveness": 70})
    settings_status = agent.set_settings(settings)
    dismissed = agent.dismiss_candidate(candidate_id)

    status = agent.status()
    assert settings_status.settings.aggressiveness == 70
    assert dismissed is not None
    assert status.candidate_interventions == []
    assert status.runtime_state == "idle_listening"


def test_agent_stores_requirement_clarifying_question_silently() -> None:
    agent = MeetingAgentOrchestrator(mode="facilitator")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    status = agent.status()
    assert status.runtime_state == "candidate_intervention"
    assert status.candidate_interventions[0].type == "clarifying_question"
    assert status.candidate_interventions[0].speak_allowed is False
    assert "acceptance criteria" in status.candidate_interventions[0].text
    assert len(status.requirements) == 1
    assert status.requirements[0].text == "We need users to approve invoices before payment."
    assert status.requirements[0].open_questions


def test_agent_extracts_richer_requirement_fields() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript(
            "u1",
            "Speaker_1",
            (
                "Users must approve invoices before payment so finance can audit spend. "
                "Priority: critical. Owner: Jane"
            ),
        )
    )

    requirement = agent.status().requirements[0]
    assert requirement.actor == "Users"
    assert requirement.behavior == "approve invoices before payment"
    assert requirement.goal == "finance can audit spend"
    assert requirement.constraints == ["before payment"]
    assert requirement.priority == "high"
    assert requirement.owner == "Jane"
    assert requirement.status == "clarifying"


def test_agent_extracts_requirement_acceptance_criteria() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript(
            "u1",
            "Speaker_1",
            (
                "We need users to approve invoices before payment. "
                "Acceptance criteria: audit trail is saved; approver sees confirmation. "
                "Owner: Jane"
            ),
        )
    )

    requirement = agent.status().requirements[0]
    assert requirement.acceptance_criteria == [
        "audit trail is saved",
        "approver sees confirmation",
    ]
    assert requirement.owner == "Jane"


def test_agent_merges_requirement_acceptance_criteria() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript(
            "u1",
            "Speaker_1",
            (
                "We need users to approve invoices before payment. "
                "Acceptance criteria: audit trail is saved."
            ),
        )
    )
    agent.observe_transcript(
        _live_transcript(
            "u2",
            "Speaker_2",
            (
                "Users must approve invoices before payment. "
                "Done when approver sees confirmation."
            ),
        )
    )

    requirement = agent.status().requirements[0]
    assert requirement.source_utterance_ids == ["u1", "u2"]
    assert requirement.acceptance_criteria == [
        "audit trail is saved",
        "approver sees confirmation",
    ]


def test_agent_uses_fake_llm_for_requirement_candidate() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(
            [
                AgentReasoningDecision(
                    action="ask_clarifying_question",
                    candidate_type="clarifying_question",
                    text="Which invoice roles can approve payment?",
                    score=0.81,
                    reason="fake llm wants role clarity",
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    status = agent.status()
    candidate = status.candidate_interventions[0]
    assert candidate.text == "Which invoice roles can approve payment?"
    assert candidate.score == 0.81
    assert candidate.reason == "fake llm wants role clarity"
    assert candidate.speak_allowed is False
    assert len(status.reasoning_traces) == 1
    assert status.reasoning_traces[0].utterance_id == "u1"
    assert status.reasoning_traces[0].action == "ask_clarifying_question"
    assert status.reasoning_traces[0].candidate_type == "clarifying_question"
    assert status.reasoning_traces[0].score == 0.81
    assert status.reasoning_traces[0].reason == "fake llm wants role clarity"
    assert status.reasoning_traces[0].error is None
    assert status.llm_call_traces[-1].operation == "reasoning"
    assert status.llm_call_traces[-1].success is True
    assert status.llm_call_traces[-1].input_preview == (
        "We need users to approve invoices before payment."
    )
    assert status.llm_call_traces[-1].output_preview == "fake llm wants role clarity"
    assert status.last_error is None


def test_agent_llm_listen_decision_fails_closed_without_candidate() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(
            [AgentReasoningDecision(action="listen", score=0.0, reason="nothing useful")]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    status = agent.status()
    assert status.runtime_state == "idle_listening"
    assert status.candidate_interventions == []
    assert status.last_error is None


def test_agent_llm_error_fails_closed_and_records_error() -> None:
    agent = MeetingAgentOrchestrator(mode="passive", llm_client=_FailingLLMClient())
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    status = agent.status()
    assert status.runtime_state == "idle_listening"
    assert status.candidate_interventions == []
    assert status.last_error == "reasoning failed: TimeoutError: timed out"
    assert status.llm_call_traces[-1].operation == "reasoning"
    assert status.llm_call_traces[-1].success is False
    assert status.llm_call_traces[-1].error == "TimeoutError: timed out"
    assert len(status.reasoning_traces) == 1
    assert status.reasoning_traces[0].utterance_id == "u1"
    assert status.reasoning_traces[0].action is None
    assert status.reasoning_traces[0].error == "reasoning failed: TimeoutError: timed out"


def test_agent_llm_malformed_candidate_fails_closed() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(
            [
                AgentReasoningDecision(
                    action="ask_clarifying_question",
                    score=0.6,
                    reason="missing candidate fields",
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    status = agent.status()
    assert status.runtime_state == "idle_listening"
    assert status.candidate_interventions == []
    assert status.last_error == "reasoning failed: candidate decision missing type or text"


def test_agent_llm_mode_change_candidate_requires_manual_apply() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(
            [
                AgentReasoningDecision(
                    action="suggest_mode_change",
                    candidate_type="mode_change",
                    text="Switch to facilitator mode for active requirements discovery.",
                    score=0.88,
                    reason="multiple unresolved requirement questions need facilitation",
                    suggested_mode="facilitator",
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Several requirements are open."))

    status = agent.status()
    assert status.mode == "passive"
    assert status.runtime_state == "candidate_intervention"
    candidate = status.candidate_interventions[0]
    assert candidate.type == "mode_change"
    assert candidate.suggested_mode == "facilitator"
    assert candidate.speak_allowed is False
    assert status.reasoning_traces[0].action == "suggest_mode_change"
    assert status.reasoning_traces[0].suggested_mode == "facilitator"

    applied = agent.apply_candidate(candidate.candidate_id)

    status = agent.status()
    assert applied is not None
    assert status.mode == "facilitator"
    assert status.runtime_state == "manual_override"
    assert status.candidate_interventions == []


def test_agent_llm_malformed_mode_change_fails_closed() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(
            [
                AgentReasoningDecision(
                    action="suggest_mode_change",
                    candidate_type="mode_change",
                    text="Switch modes.",
                    score=0.6,
                    reason="missing suggested mode",
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Several requirements are open."))

    status = agent.status()
    assert status.mode == "passive"
    assert status.candidate_interventions == []
    assert status.last_error == "reasoning failed: mode change decision missing suggested mode"


def test_agent_uses_llm_for_general_summary_checkpoint_candidate() -> None:
    agent = MeetingAgentOrchestrator(
        mode="scribe",
        llm_client=FakeLLMClient(
            [
                AgentReasoningDecision(
                    action="summarize",
                    candidate_type="summary_checkpoint",
                    text="Checkpoint: invoice approval scope is still open.",
                    score=0.77,
                    reason="topic shift detected",
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "That wraps the invoice flow."))

    status = agent.status()
    assert status.runtime_state == "candidate_intervention"
    assert status.candidate_interventions[0].type == "summary_checkpoint"
    assert status.candidate_interventions[0].text == (
        "Checkpoint: invoice approval scope is still open."
    )
    assert status.candidate_interventions[0].reason == "topic shift detected"


def test_agent_llm_capture_decision_updates_memory_without_candidate() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(
            [
                AgentReasoningDecision(
                    action="capture_decision",
                    text="use Google Meet first",
                    score=0.7,
                    reason="group reached consensus",
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Okay, Google Meet first."))

    status = agent.status()
    assert status.runtime_state == "idle_listening"
    assert status.candidate_interventions == []
    assert len(status.decisions) == 1
    assert status.decisions[0].text == "use Google Meet first"
    assert status.decisions[0].source_utterance_ids == ["u1"]


def test_agent_llm_requirement_refinement_updates_existing_requirement() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        llm_client=FakeLLMClient(
            [
                AgentReasoningDecision(
                    action="listen",
                    score=0.0,
                    reason="requirement fields refined",
                    requirement_refinement=RequirementRefinement(
                        actor="Finance managers",
                        behavior="approve invoices before payment",
                        goal="audit spend",
                        constraints=["before payment", "only if assigned as approver"],
                        priority="high",
                        owner="Jane",
                        status="accepted",
                        acceptance_criteria=[
                            "approval event is written to the audit trail",
                            "requester sees the approver name",
                        ],
                        open_questions=["Which backup approvers are allowed?"],
                    ),
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    status = agent.status()
    assert len(status.requirements) == 1
    requirement = status.requirements[0]
    assert requirement.actor == "Finance managers"
    assert requirement.behavior == "approve invoices before payment"
    assert requirement.goal == "audit spend"
    assert requirement.constraints == ["before payment", "only if assigned as approver"]
    assert requirement.priority == "high"
    assert requirement.owner == "Jane"
    assert requirement.status == "accepted"
    assert requirement.acceptance_criteria == [
        "approval event is written to the audit trail",
        "requester sees the approver name",
    ]
    assert "Which backup approvers are allowed?" in requirement.open_questions
    assert requirement.source_utterance_ids == ["u1"]
    assert status.candidate_interventions == []
    assert status.last_error is None


def test_create_llm_client_selects_configured_provider() -> None:
    from backend.agent import OpenAIResponsesLLMClient, create_llm_client

    assert create_llm_client("none") is None
    assert isinstance(create_llm_client("fake"), FakeLLMClient)
    assert isinstance(
        create_llm_client(
            "openai",
            api_key="test",
            model="gpt-test",
            reasoning_prompt_suffix="Prefer clarifying questions.",
            direct_answer_prompt_suffix="Be concise.",
            context_summary_prompt_suffix="Mention decisions.",
        ),
        OpenAIResponsesLLMClient,
    )


def test_facilitator_waits_for_safe_turn_before_auto_clarifying_question() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(
        mode="facilitator",
        config=AgentConfig(proactive_min_silence_ms=1_000.0, proactive_min_aggressiveness=60),
    )
    agent.set_settings(AgentSettings(aggressiveness=80))
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment."),
        speaker=speaker,
    )

    waiting_status = agent.status()
    assert waiting_status.runtime_state == "waiting_for_turn"
    assert waiting_status.candidate_interventions[0].speak_allowed is False
    assert speaker.spoken == []

    agent.observe_silence(3_200.0, speaker=speaker)

    status = agent.status()
    assert status.runtime_state == "speaking"
    assert status.candidate_interventions[0].speak_allowed is True
    assert speaker.spoken == [
        "What acceptance criteria should we use for: users to approve invoices before payment?"
    ]


def test_agent_settings_control_silence_threshold_and_cooldown() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(
        mode="facilitator",
        config=AgentConfig(proactive_min_aggressiveness=60),
    )
    agent.set_settings(
        AgentSettings(
            aggressiveness=100,
            proactive_min_silence_ms=5_000.0,
            direct_answer_cooldown_ms=60_000.0,
        )
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment."),
        speaker=speaker,
    )
    agent.observe_silence(3_500.0, speaker=speaker)
    assert speaker.spoken == []

    agent.observe_silence(7_500.0, speaker=speaker)
    assert speaker.spoken == [
        "What acceptance criteria should we use for: users to approve invoices before payment?"
    ]

    agent.observe_speech_result(
        job_id="job-1",
        completed_at_ms=now_ms(),
        error=None,
        interrupted=False,
    )
    agent.observe_transcript(
        _live_transcript("u2", "Speaker_1", "Can Erica summarize?"),
        speaker=speaker,
    )

    status = agent.status()
    assert status.candidate_interventions[-1].type == "direct_answer"
    assert status.candidate_interventions[-1].speak_allowed is False
    assert len(speaker.spoken) == 1


def test_passive_mode_never_auto_speaks_requirement_candidate() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.set_settings(AgentSettings(aggressiveness=100))
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment."),
        speaker=speaker,
    )

    agent.observe_silence(20_000.0, speaker=speaker)

    status = agent.status()
    assert status.runtime_state == "candidate_intervention"
    assert status.candidate_interventions[0].speak_allowed is False
    assert speaker.spoken == []


def test_readiness_blocks_facilitator_auto_speak() -> None:
    speaker = _FakeSpeaker()
    agent = MeetingAgentOrchestrator(
        mode="facilitator",
        config=AgentConfig(proactive_min_silence_ms=1_000.0, proactive_min_aggressiveness=60),
    )
    agent.set_settings(AgentSettings(aggressiveness=100))
    agent.set_readiness(AgentReadiness(can_auto_speak=False, blockers=["tts disabled"]))
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment."),
        speaker=speaker,
    )

    agent.observe_silence(20_000.0, speaker=speaker)

    status = agent.status()
    assert status.readiness.can_auto_speak is False
    assert status.readiness.blockers == ["tts disabled"]
    assert status.runtime_state == "waiting_for_turn"
    assert status.candidate_interventions[0].speak_allowed is False
    assert speaker.spoken == []


def test_agent_tracks_questions_and_decisions() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "We decided to launch on Friday."))

    status = agent.status()
    assert len(status.open_questions) == 1
    assert status.open_questions[0].text == "What is the launch date?"
    assert len(status.decisions) == 1
    assert status.decisions[0].text == "launch on friday"


def test_agent_marks_related_open_question_answered() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "The launch date is Friday."))

    question = agent.status().open_questions[0]
    assert question.answered is True
    assert question.source_utterance_ids == ["u1", "u2"]


def test_agent_marks_decisions_confirmed_and_action_items_completed() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "We decided to launch Friday."))
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "Confirmed: launch Friday."))
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "Action item: confirm owners."))
    agent.observe_transcript(_live_transcript("u4", "Speaker_2", "Completed: confirm owners."))

    status = agent.status()
    assert len(status.decisions) == 1
    assert status.decisions[0].confirmed is True
    assert status.decisions[0].source_utterance_ids == ["u1", "u2"]
    assert len(status.action_items) == 1
    assert status.action_items[0].completed is True
    assert status.action_items[0].source_utterance_ids == ["u3", "u4"]


def test_agent_links_related_questions_to_requirements() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )
    agent.observe_transcript(
        _live_transcript("u2", "Speaker_2", "Which users can approve invoices?")
    )

    status = agent.status()
    assert len(status.requirements) == 1
    assert len(status.open_questions) == 1
    assert status.open_questions[0].related_requirement_ids == [
        status.requirements[0].requirement_id
    ]


def test_agent_merges_question_requirement_links() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "Which users approve invoices?"))
    agent.observe_transcript(_live_transcript("u3", "Speaker_3", "Which users approve invoices?"))

    status = agent.status()
    assert len(status.open_questions) == 1
    assert status.open_questions[0].source_utterance_ids == ["u2", "u3"]
    assert status.open_questions[0].related_requirement_ids == [
        status.requirements[0].requirement_id
    ]


def test_agent_tracks_action_items_and_risks() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Action item: confirm owners."))
    agent.observe_transcript(
        _live_transcript("u2", "Speaker_2", "Risk: launch could slip if QA is blocked.")
    )

    status = agent.status()
    assert len(status.action_items) == 1
    assert status.action_items[0].text == "confirm owners"
    assert len(status.risks) == 1
    assert status.risks[0].text == "launch could slip if qa is blocked"
    assert status.risks[0].severity == "high"


def test_agent_builds_context_summary_checkpoints() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        config=AgentConfig(context_summary_utterance_interval=3),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript(
            "u1",
            "Speaker_1",
            "We need an approval flow. Acceptance criteria: manager can approve.",
        )
    )
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "We decided to launch Friday."))

    status = agent.status()
    assert len(status.context_summaries) == 1
    checkpoint = status.context_summaries[0]
    assert checkpoint.start_utterance_id == "u1"
    assert checkpoint.end_utterance_id == "u3"
    assert checkpoint.utterance_count == 3
    assert "3 utterances from 2 speakers" in checkpoint.text
    assert "approval flow" in checkpoint.text


def test_agent_uses_llm_context_summary_when_available() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        config=AgentConfig(context_summary_utterance_interval=3),
        llm_client=FakeLLMClient(
            context_summaries=[
                (
                    "Invoice approvals need audit trails, launch timing is open, "
                    "and Friday launch was captured."
                )
            ]
        ),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need an approval flow.")
    )
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "We decided to launch Friday."))

    status = agent.status()
    assert len(status.context_summaries) == 1
    assert status.context_summaries[0].text == (
        "Invoice approvals need audit trails, launch timing is open, "
        "and Friday launch was captured."
    )
    assert status.context_summaries[0].topics
    assert any(
        trace.operation == "context_summary"
        and trace.success
        and trace.output_preview
        == (
            "Invoice approvals need audit trails, launch timing is open, "
            "and Friday launch was captured."
        )
        for trace in status.llm_call_traces
    )
    assert status.last_error is None


def test_agent_context_summary_falls_back_when_llm_fails() -> None:
    agent = MeetingAgentOrchestrator(
        mode="passive",
        config=AgentConfig(context_summary_utterance_interval=3),
        llm_client=_FailingContextSummaryLLMClient(),
    )
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need an approval flow.")
    )
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "We decided to launch Friday."))

    status = agent.status()
    assert len(status.context_summaries) == 1
    assert "3 utterances from 2 speakers" in status.context_summaries[0].text
    assert any(
        trace.operation == "context_summary" and not trace.success
        for trace in status.llm_call_traces
    )


def test_agent_tracks_current_topic_from_requirements_and_explicit_topic() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    status = agent.status()
    assert status.current_topic is not None
    assert status.current_topic.topic == "approve invoices before payment"
    assert status.current_topic.source_utterance_id == "u1"

    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "Next topic is rollout."))

    status = agent.status()
    assert status.current_topic is not None
    assert status.current_topic.topic == "rollout"
    assert status.current_topic.source_utterance_id == "u2"


def test_agent_passes_current_topic_to_llm() -> None:
    llm = _CapturingLLMClient()
    agent = MeetingAgentOrchestrator(mode="passive", llm_client=llm)
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "We need users to approve invoices before payment.")
    )

    assert llm.contexts
    assert llm.contexts[0].current_topic == "approve invoices before payment"


def test_agent_tracks_parked_topics() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Parking lot: Zoom support."))
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "Let's park browser support."))
    agent.observe_transcript(
        _live_transcript("u3", "Speaker_1", "Put pricing review in the parking lot.")
    )

    status = agent.status()
    assert [item.text for item in status.parked_topics] == [
        "zoom support",
        "browser support",
        "pricing review",
    ]


def test_agent_merges_duplicate_structured_records() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript(
            "u1",
            "Speaker_1",
            "We need an approval flow. Acceptance criteria: manager can approve.",
        )
    )
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "we need an approval flow"))
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u4", "Speaker_2", "what is the launch date"))
    agent.observe_transcript(_live_transcript("u5", "Speaker_1", "We decided to launch Friday."))
    agent.observe_transcript(_live_transcript("u6", "Speaker_2", "We decided launch Friday."))
    agent.observe_transcript(_live_transcript("u7", "Speaker_1", "Action item: confirm owners."))
    agent.observe_transcript(_live_transcript("u8", "Speaker_2", "todo: confirm owners"))
    agent.observe_transcript(_live_transcript("u9", "Speaker_1", "Risk: QA might be blocked."))
    agent.observe_transcript(_live_transcript("u10", "Speaker_2", "risk QA might be blocked"))
    agent.observe_transcript(_live_transcript("u11", "Speaker_1", "Parking lot: Zoom support."))
    agent.observe_transcript(_live_transcript("u12", "Speaker_2", "follow-up: zoom support"))

    status = agent.status()
    assert len(status.requirements) == 1
    assert status.requirements[0].source_utterance_ids == ["u1", "u2"]
    assert len(status.open_questions) == 1
    assert status.open_questions[0].source_utterance_ids == ["u3", "u4", "u5"]
    assert status.open_questions[0].answered is True
    assert len(status.decisions) == 1
    assert status.decisions[0].source_utterance_ids == ["u5", "u6"]
    assert len(status.action_items) == 1
    assert status.action_items[0].source_utterance_ids == ["u7", "u8"]
    assert len(status.risks) == 1
    assert status.risks[0].source_utterance_ids == ["u9", "u10"]
    assert len(status.parked_topics) == 1
    assert status.parked_topics[0].source_utterance_ids == ["u11", "u12"]


def test_agent_merges_conservative_semantic_duplicate_records() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(
        _live_transcript("u1", "Speaker_1", "Users must approve invoices before payment.")
    )
    agent.observe_transcript(
        _live_transcript("u2", "Speaker_2", "We need users to approve invoices before payment.")
    )
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u4", "Speaker_2", "Launch date?"))
    agent.observe_transcript(_live_transcript("u5", "Speaker_1", "We decided to launch Friday."))
    agent.observe_transcript(_live_transcript("u6", "Speaker_2", "Decision is launch Friday."))
    agent.observe_transcript(_live_transcript("u7", "Speaker_1", "Action item: confirm owners."))
    agent.observe_transcript(_live_transcript("u8", "Speaker_2", "To do: confirm owners."))
    agent.observe_transcript(_live_transcript("u9", "Speaker_1", "Risk: QA is blocked."))
    agent.observe_transcript(_live_transcript("u10", "Speaker_2", "Concern: QA is blocked."))
    agent.observe_transcript(_live_transcript("u11", "Speaker_1", "Parking lot: Zoom support."))
    agent.observe_transcript(_live_transcript("u12", "Speaker_2", "Parked topic: Zoom support."))

    status = agent.status()
    assert len(status.requirements) == 1
    assert status.requirements[0].source_utterance_ids == ["u1", "u2"]
    assert len(status.open_questions) == 1
    assert status.open_questions[0].source_utterance_ids == ["u3", "u4", "u5"]
    assert status.open_questions[0].answered is True
    assert len(status.decisions) == 1
    assert status.decisions[0].source_utterance_ids == ["u5", "u6"]
    assert len(status.action_items) == 1
    assert status.action_items[0].source_utterance_ids == ["u7", "u8"]
    assert len(status.risks) == 1
    assert status.risks[0].source_utterance_ids == ["u9", "u10"]
    assert len(status.parked_topics) == 1
    assert status.parked_topics[0].source_utterance_ids == ["u11", "u12"]


def test_agent_end_meeting_generates_summary_artifact(tmp_path: Path) -> None:
    agent = MeetingAgentOrchestrator(mode="passive", summary_dir=tmp_path)
    agent.begin_meeting(
        AgentBeginMeetingRequest(meeting_id="meeting-1", meeting_url="https://meet.google.com/a")
    )
    agent.observe_transcript(
        _live_transcript(
            "u1",
            "Speaker_1",
            "We need an approval flow. Acceptance criteria: manager can approve.",
        )
    )
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "We decided to launch Friday."))
    agent.observe_transcript(_live_transcript("u4", "Speaker_2", "Action item: confirm owners."))
    agent.observe_transcript(_live_transcript("u5", "Speaker_1", "Risk: QA might be blocked."))
    agent.observe_transcript(_live_transcript("u6", "Speaker_2", "Parking lot: Zoom support."))

    status = agent.end_meeting()
    summary = agent.latest_summary()

    assert status.lifecycle_state == "meeting_ended"
    assert status.latest_summary is not None
    assert summary is not None
    assert summary.meeting_id == "meeting-1"
    assert summary.meeting_url == "https://meet.google.com/a"
    assert summary.utterance_count == 6
    assert summary.participant_count == 2
    assert summary.requirements[0].text == "We need an approval flow."
    assert summary.requirements[0].acceptance_criteria == ["manager can approve"]
    assert summary.open_questions[0].text == "What is the launch date?"
    assert summary.decisions[0].text == "launch friday"
    assert summary.action_items[0].text == "confirm owners"
    assert summary.risks[0].text == "qa might be blocked"
    assert summary.parked_topics[0].text == "zoom support"
    assert isinstance(summary.context_summaries, list)
    assert summary.current_topic is not None
    assert summary.current_topic.topic == "an approval flow"
    assert summary.json_path is not None
    assert summary.markdown_path is not None
    assert Path(summary.json_path).exists()
    assert Path(summary.markdown_path).exists()
    assert "# Erica Meeting Summary" in summary.markdown
    assert "## Requirements" in summary.markdown
    assert "## Action Items" in summary.markdown
    assert "## Risks" in summary.markdown
    assert "## Parked Topics" in summary.markdown
    assert "## Context Checkpoints" in summary.markdown
    assert "## Current Topic" in summary.markdown
    assert "- We need an approval flow." in summary.markdown
    assert "status: clarifying" in summary.markdown
    assert "acceptance: manager can approve" in summary.markdown
    assert "- zoom support" in summary.markdown
    assert "qa might be blocked" in Path(summary.markdown_path).read_text(encoding="utf-8")
    assert '"meeting_id": "meeting-1"' in Path(summary.json_path).read_text(encoding="utf-8")


def test_agent_summary_filters_answered_questions_and_marks_record_status(tmp_path: Path) -> None:
    agent = MeetingAgentOrchestrator(mode="passive", summary_dir=tmp_path)
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "What is the launch date?"))
    agent.observe_transcript(_live_transcript("u2", "Speaker_2", "The launch date is Friday."))
    agent.observe_transcript(_live_transcript("u3", "Speaker_1", "We decided to launch Friday."))
    agent.observe_transcript(_live_transcript("u4", "Speaker_2", "Confirmed: launch Friday."))
    agent.observe_transcript(_live_transcript("u5", "Speaker_1", "Action item: confirm owners."))
    agent.observe_transcript(_live_transcript("u6", "Speaker_2", "Completed: confirm owners."))

    summary = agent.end_meeting().latest_summary

    assert summary is not None
    assert summary.open_questions[0].answered is True
    assert summary.decisions[0].confirmed is True
    assert summary.action_items[0].completed is True
    assert "- None captured." in summary.markdown
    assert "- launch friday (confirmed)" in summary.markdown
    assert "- confirm owners (completed)" in summary.markdown


def test_agent_begin_meeting_resets_structured_memory() -> None:
    agent = MeetingAgentOrchestrator(mode="passive")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))
    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "We need an approval flow."))
    assert agent.status().requirements

    status = agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-2"))

    assert status.meeting_id == "meeting-2"
    assert status.requirements == []
    assert status.open_questions == []
    assert status.decisions == []
    assert status.parked_topics == []
    assert status.context_summaries == []
    assert status.llm_call_traces == []
    assert status.current_topic is None
    assert status.reasoning_traces == []


def test_agent_off_mode_ignores_transcripts() -> None:
    agent = MeetingAgentOrchestrator(mode="off")
    agent.begin_meeting(AgentBeginMeetingRequest(meeting_id="meeting-1"))

    agent.observe_transcript(_live_transcript("u1", "Speaker_1", "Hey Erica, are you there?"))

    status = agent.status()
    assert status.recent_utterances == []
    assert status.candidate_interventions == []


@dataclass
class _FakeSpeaker:
    spoken: list[str] | None = None

    def __post_init__(self) -> None:
        self.spoken = []

    def enqueue(self, text: str, *, interrupt: bool = False) -> object:
        _ = interrupt
        assert self.spoken is not None
        self.spoken.append(text)
        return SimpleNamespace(job_id=f"job-{len(self.spoken)}")


class _FailingLLMClient:
    def decide(self, context: ReasoningContext) -> AgentReasoningDecision:
        _ = context
        raise TimeoutError("timed out")

    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        _ = context
        raise TimeoutError("timed out")

    def summarize_context(self, context: ContextSummaryRequest) -> str:
        _ = context
        raise TimeoutError("timed out")


class _FailingDirectAnswerLLMClient:
    def decide(self, context: ReasoningContext) -> AgentReasoningDecision:
        _ = context
        return AgentReasoningDecision(action="listen", score=0.0, reason="unused")

    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        _ = context
        raise TimeoutError("timed out")

    def summarize_context(self, context: ContextSummaryRequest) -> str:
        _ = context
        return "unused"


class _FailingContextSummaryLLMClient:
    def decide(self, context: ReasoningContext) -> AgentReasoningDecision:
        _ = context
        return AgentReasoningDecision(action="listen", score=0.0, reason="unused")

    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        _ = context
        return "unused"

    def summarize_context(self, context: ContextSummaryRequest) -> str:
        _ = context
        raise TimeoutError("timed out")


class _CapturingLLMClient:
    def __init__(self) -> None:
        self.contexts: list[ReasoningContext] = []

    def decide(self, context: ReasoningContext) -> AgentReasoningDecision:
        self.contexts.append(context)
        return AgentReasoningDecision(action="listen", score=0.0, reason="captured context")

    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        _ = context
        return "unused"

    def summarize_context(self, context: ContextSummaryRequest) -> str:
        _ = context
        return "unused"


def _live_transcript(utterance_id: str, speaker: str, text: str) -> LiveTranscript:
    window = UtteranceWindow(
        window_id=utterance_id,
        session_id="meeting-1",
        source_wav="live://meeting-1",
        sample_rate=16_000,
        vad_provider="rms",
        start_ms=1_000.0,
        end_ms=2_000.0,
        duration_ms=1_000.0,
        padded_start_ms=900.0,
        padded_end_ms=2_100.0,
        padded_duration_ms=1_200.0,
        start_sequence=1,
        end_sequence=4,
        peak=0.2,
        mean_rms=0.1,
    )
    transcript = SttTranscript(
        window_id=utterance_id,
        provider="fake",
        model_id="fake",
        text=text,
        language="en",
        confidence=0.9,
        wall_time_s=0.01,
        error=None,
    )
    utterance = Utterance(
        utterance_id=utterance_id,
        session_id="meeting-1",
        speaker=speaker,
        start_ts=1.0,
        end_ts=2.0,
        start_ms=1_000.0,
        end_ms=2_000.0,
        text=text,
        is_final=True,
        confidence=0.9,
        speaker_confidence=0.8,
        stt_provider="fake",
        stt_model="fake",
        vad_provider="rms",
        raw_audio_ref="live://meeting-1",
    )
    return LiveTranscript(
        window=window,
        transcript=transcript,
        speaker=SpeakerAttribution(speaker=speaker, confidence=0.8, method="fake"),
        utterance=utterance,
        completed_at_ms=2_100.0,
    )
