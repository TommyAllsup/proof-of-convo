from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from backend.agent.reasoner import (
    ContextSummaryRequest,
    DeterministicMeetingReasoner,
    DirectAnswerContext,
    LLMClient,
    MeetingReasoner,
    ReasoningContext,
)
from backend.audio.live_stt import LiveTranscript
from backend.audio.manager import now_ms
from backend.models.agent import (
    ActionItemRecord,
    AgentBeginMeetingRequest,
    AgentCandidateIntervention,
    AgentLLMCallTrace,
    AgentParticipationMode,
    AgentReadiness,
    AgentReasoningDecision,
    AgentReasoningTrace,
    AgentRuntimeState,
    AgentSettings,
    AgentStatus,
    AgentUtterance,
    CurrentTopicState,
    DecisionRecord,
    MeetingContextSummary,
    MeetingLifecycleState,
    MeetingSummaryArtifact,
    OpenQuestionRecord,
    ParkedTopicRecord,
    ParticipantState,
    RequirementPriority,
    RequirementRecord,
    RequirementRefinement,
    RequirementStatus,
    RiskRecord,
)


class SpeechEnqueuer(Protocol):
    def enqueue(self, text: str, *, interrupt: bool = False) -> object: ...


class TextRecord(Protocol):
    text: str
    source_utterance_ids: list[str]


@dataclass(frozen=True)
class RequirementFields:
    actor: str | None = None
    goal: str | None = None
    behavior: str | None = None
    constraints: tuple[str, ...] = ()
    priority: RequirementPriority = "unknown"
    owner: str | None = None
    status: RequirementStatus = "proposed"
    acceptance_criteria: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentConfig:
    direct_answer_cooldown_ms: float = 8_000.0
    proactive_min_silence_ms: float = 1_200.0
    proactive_min_aggressiveness: int = 60
    max_recent_utterances: int = 50
    max_candidates: int = 20
    max_requirements: int = 50
    max_open_questions: int = 50
    max_decisions: int = 50
    max_action_items: int = 50
    max_risks: int = 50
    max_parked_topics: int = 50
    max_context_summaries: int = 24
    max_reasoning_traces: int = 30
    max_llm_call_traces: int = 30
    context_summary_utterance_interval: int = 6


class MeetingAgentOrchestrator:
    def __init__(
        self,
        *,
        mode: AgentParticipationMode = "passive",
        config: AgentConfig | None = None,
        reasoner: MeetingReasoner | None = None,
        llm_client: LLMClient | None = None,
        summary_dir: Path | None = None,
    ) -> None:
        self._config = config or AgentConfig()
        self._reasoner = reasoner or DeterministicMeetingReasoner()
        self._llm_client = llm_client
        self._summary_dir = summary_dir
        self._mode = mode
        self._lifecycle_state: MeetingLifecycleState = "not_in_meeting"
        self._runtime_state: AgentRuntimeState = "idle_listening"
        self._meeting_id: str | None = None
        self._meeting_url: str | None = None
        self._recent_utterances: deque[AgentUtterance] = deque(
            maxlen=self._config.max_recent_utterances
        )
        self._participants: dict[str, ParticipantState] = {}
        self._candidate_interventions: deque[AgentCandidateIntervention] = deque(
            maxlen=self._config.max_candidates
        )
        self._requirements: deque[RequirementRecord] = deque(maxlen=self._config.max_requirements)
        self._open_questions: deque[OpenQuestionRecord] = deque(
            maxlen=self._config.max_open_questions
        )
        self._decisions: deque[DecisionRecord] = deque(maxlen=self._config.max_decisions)
        self._action_items: deque[ActionItemRecord] = deque(
            maxlen=self._config.max_action_items
        )
        self._risks: deque[RiskRecord] = deque(maxlen=self._config.max_risks)
        self._parked_topics: deque[ParkedTopicRecord] = deque(
            maxlen=self._config.max_parked_topics
        )
        self._context_summaries: deque[MeetingContextSummary] = deque(
            maxlen=self._config.max_context_summaries
        )
        self._reasoning_traces: deque[AgentReasoningTrace] = deque(
            maxlen=self._config.max_reasoning_traces
        )
        self._llm_call_traces: deque[AgentLLMCallTrace] = deque(
            maxlen=self._config.max_llm_call_traces
        )
        self._last_context_summary_utterance_count = 0
        self._current_topic: CurrentTopicState | None = None
        self._last_agent_speech_at_ms: float | None = None
        self._last_human_speech_at_ms: float | None = None
        self._active_speech_job_id: str | None = None
        self._last_speech_job_id: str | None = None
        self._settings = AgentSettings(
            direct_answer_cooldown_ms=self._config.direct_answer_cooldown_ms,
            proactive_min_silence_ms=self._config.proactive_min_silence_ms,
        )
        self._readiness = AgentReadiness()
        self._latest_summary: MeetingSummaryArtifact | None = None
        self._last_state_change_at_ms = now_ms()
        self._last_error: str | None = None

    def status(self) -> AgentStatus:
        self._refresh_runtime_state()
        return AgentStatus(
            mode=self._mode,
            lifecycle_state=self._lifecycle_state,
            runtime_state=self._runtime_state,
            meeting_id=self._meeting_id,
            meeting_url=self._meeting_url,
            recent_utterances=list(self._recent_utterances),
            participants=list(self._participants.values()),
            requirements=list(self._requirements),
            open_questions=list(self._open_questions),
            decisions=list(self._decisions),
            action_items=list(self._action_items),
            risks=list(self._risks),
            parked_topics=list(self._parked_topics),
            context_summaries=list(self._context_summaries),
            current_topic=self._current_topic,
            candidate_interventions=list(self._candidate_interventions),
            reasoning_traces=list(self._reasoning_traces),
            llm_call_traces=list(self._llm_call_traces),
            latest_summary=self._latest_summary,
            settings=self._settings,
            readiness=self._readiness,
            active_speech_job_id=self._active_speech_job_id,
            last_speech_job_id=self._last_speech_job_id,
            last_agent_speech_at_ms=self._last_agent_speech_at_ms,
            last_human_speech_at_ms=self._last_human_speech_at_ms,
            last_state_change_at_ms=self._last_state_change_at_ms,
            last_error=self._last_error,
        )

    def set_mode(self, mode: AgentParticipationMode) -> AgentStatus:
        self._mode = mode
        self._transition_runtime("idle_listening")
        if mode == "off":
            self._candidate_interventions.clear()
        return self.status()

    def set_settings(self, settings: AgentSettings) -> AgentStatus:
        self._settings = settings
        return self.status()

    def set_readiness(self, readiness: AgentReadiness) -> AgentStatus:
        self._readiness = readiness
        return self.status()

    def begin_meeting(self, request: AgentBeginMeetingRequest) -> AgentStatus:
        current = now_ms()
        self._meeting_id = request.meeting_id or uuid.uuid4().hex[:12]
        self._meeting_url = request.meeting_url
        self._recent_utterances.clear()
        self._participants.clear()
        self._candidate_interventions.clear()
        self._requirements.clear()
        self._open_questions.clear()
        self._decisions.clear()
        self._action_items.clear()
        self._risks.clear()
        self._parked_topics.clear()
        self._context_summaries.clear()
        self._reasoning_traces.clear()
        self._llm_call_traces.clear()
        self._last_context_summary_utterance_count = 0
        self._current_topic = None
        self._latest_summary = None
        self._last_agent_speech_at_ms = None
        self._last_human_speech_at_ms = None
        self._active_speech_job_id = None
        self._last_speech_job_id = None
        self._last_error = None
        self._lifecycle_state = "in_meeting"
        self._runtime_state = "idle_listening"
        self._last_state_change_at_ms = current
        return self.status()

    def end_meeting(self) -> AgentStatus:
        self._latest_summary = self._build_summary()
        self._lifecycle_state = "meeting_ended"
        self._transition_runtime("idle_listening")
        return self.status()

    def reset(self) -> AgentStatus:
        self._lifecycle_state = "not_in_meeting"
        self._meeting_id = None
        self._meeting_url = None
        self._recent_utterances.clear()
        self._participants.clear()
        self._candidate_interventions.clear()
        self._requirements.clear()
        self._open_questions.clear()
        self._decisions.clear()
        self._action_items.clear()
        self._risks.clear()
        self._parked_topics.clear()
        self._context_summaries.clear()
        self._reasoning_traces.clear()
        self._llm_call_traces.clear()
        self._last_context_summary_utterance_count = 0
        self._current_topic = None
        self._latest_summary = None
        self._last_agent_speech_at_ms = None
        self._last_human_speech_at_ms = None
        self._active_speech_job_id = None
        self._last_speech_job_id = None
        self._last_error = None
        self._transition_runtime("idle_listening")
        return self.status()

    def observe_session_start(self, *, session_id: str, meeting_url: str | None) -> None:
        if self._lifecycle_state == "not_in_meeting":
            self.begin_meeting(
                AgentBeginMeetingRequest(meeting_id=session_id, meeting_url=meeting_url)
            )

    def observe_session_stop(self) -> None:
        if self._lifecycle_state == "in_meeting":
            self._latest_summary = self._build_summary()
            self._lifecycle_state = "meeting_ended"
            self._transition_runtime("idle_listening")

    def latest_summary(self) -> MeetingSummaryArtifact | None:
        return self._latest_summary

    def observe_human_speech_start(self, event_ms: float) -> None:
        self._last_human_speech_at_ms = event_ms
        if self._runtime_state == "speaking":
            self._active_speech_job_id = None
            self._transition_runtime("interrupted")

    def observe_silence(
        self,
        event_ms: float,
        *,
        speaker: SpeechEnqueuer | None = None,
    ) -> None:
        if speaker is None or self._lifecycle_state != "in_meeting" or self._mode != "facilitator":
            return
        candidate = self._next_auto_speak_candidate(event_ms)
        if candidate is None:
            return
        self._speak_candidate(candidate, speaker=speaker, interrupt=False)

    def observe_transcript(
        self,
        transcript: LiveTranscript,
        *,
        speaker: SpeechEnqueuer | None = None,
    ) -> None:
        utterance = transcript.utterance
        text = utterance.text.strip()
        if not text or self._mode == "off" or self._lifecycle_state != "in_meeting":
            return

        received_at_ms = transcript.completed_at_ms
        self._last_human_speech_at_ms = max(self._last_human_speech_at_ms or 0.0, utterance.end_ms)
        self._recent_utterances.append(
            AgentUtterance(
                utterance_id=utterance.utterance_id,
                session_id=utterance.session_id,
                speaker=utterance.speaker,
                text=text,
                start_ms=utterance.start_ms,
                end_ms=utterance.end_ms,
                received_at_ms=received_at_ms,
            )
        )
        participant = self._participants.get(utterance.speaker)
        if participant is None:
            participant = ParticipantState(speaker=utterance.speaker)
            self._participants[utterance.speaker] = participant
        participant.utterance_count += 1
        participant.last_heard_at_ms = utterance.end_ms
        self._extract_memory_records(
            text,
            utterance_id=utterance.utterance_id,
            speaker=utterance.speaker,
            created_at_ms=received_at_ms,
        )
        self._update_memory_lifecycle(text, source_utterance_id=utterance.utterance_id)
        self._update_current_topic(
            text,
            utterance_id=utterance.utterance_id,
            updated_at_ms=received_at_ms,
        )
        self._maybe_update_context_summary()

        if self._apply_explicit_command(text):
            return

        direct_candidate = self._direct_address_candidate(text, utterance.utterance_id)
        if direct_candidate is not None:
            self._candidate_interventions.append(direct_candidate)
            if direct_candidate.speak_allowed and speaker is not None:
                self._speak_candidate(direct_candidate, speaker=speaker, interrupt=True)
            else:
                self._transition_runtime("candidate_intervention")
            return

        requirement_candidate = self._requirement_candidate(
            text,
            utterance.utterance_id,
            event_ms=received_at_ms,
        )
        if requirement_candidate is not None:
            self._candidate_interventions.append(requirement_candidate)
            if requirement_candidate.speak_allowed and speaker is not None:
                self._speak_candidate(requirement_candidate, speaker=speaker, interrupt=False)
            else:
                next_state: AgentRuntimeState = (
                    "waiting_for_turn"
                    if self._candidate_waits_for_turn(requirement_candidate)
                    else "candidate_intervention"
                )
                self._transition_runtime(next_state)
            return
        if _looks_like_requirement(text) and self._llm_client is not None:
            self._transition_runtime("idle_listening")
            return

        llm_candidate = self._llm_candidate(text, utterance.utterance_id, event_ms=received_at_ms)
        if llm_candidate is not None:
            self._candidate_interventions.append(llm_candidate)
            if llm_candidate.speak_allowed and speaker is not None:
                self._speak_candidate(llm_candidate, speaker=speaker, interrupt=False)
            else:
                self._transition_runtime("candidate_intervention")
            return

        self._transition_runtime("idle_listening")

    def speak_candidate(
        self,
        candidate_id: str,
        *,
        speaker: SpeechEnqueuer,
        interrupt: bool,
    ) -> AgentCandidateIntervention | None:
        candidate = next(
            (item for item in self._candidate_interventions if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            return None
        self._speak_candidate(candidate, speaker=speaker, interrupt=interrupt)
        return candidate

    def dismiss_candidate(self, candidate_id: str) -> AgentCandidateIntervention | None:
        candidate = next(
            (item for item in self._candidate_interventions if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            return None
        self._candidate_interventions = deque(
            (item for item in self._candidate_interventions if item.candidate_id != candidate_id),
            maxlen=self._config.max_candidates,
        )
        if not self._candidate_interventions and self._runtime_state == "candidate_intervention":
            self._transition_runtime("idle_listening")
        return candidate

    def apply_candidate(self, candidate_id: str) -> AgentCandidateIntervention | None:
        candidate = next(
            (item for item in self._candidate_interventions if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            return None
        if candidate.type != "mode_change" or candidate.suggested_mode is None:
            self._last_error = "candidate cannot be applied"
            return None
        self._mode = candidate.suggested_mode
        self._candidate_interventions = deque(
            (item for item in self._candidate_interventions if item.candidate_id != candidate_id),
            maxlen=self._config.max_candidates,
        )
        self._transition_runtime("manual_override")
        self._last_error = None
        return candidate

    def observe_speech_result(
        self,
        *,
        job_id: str,
        completed_at_ms: float,
        error: str | None,
        interrupted: bool,
    ) -> None:
        self._last_speech_job_id = job_id
        if self._active_speech_job_id == job_id:
            self._active_speech_job_id = None
        if error is not None:
            self._last_error = error
            next_state: AgentRuntimeState = (
                "candidate_intervention" if self._candidate_interventions else "idle_listening"
            )
            self._transition_runtime(next_state)
            return
        self._last_agent_speech_at_ms = completed_at_ms
        self._last_error = None
        self._transition_runtime("interrupted" if interrupted else "cooldown")

    def _apply_explicit_command(self, text: str) -> bool:
        command = _explicit_erica_command(text)
        if command is None:
            return False
        command_type, value = command
        if command_type == "mode" and value is not None:
            self._mode = value
            if value == "off":
                self._candidate_interventions.clear()
            self._transition_runtime("manual_override")
            self._last_error = None
            return True
        if command_type == "end_meeting":
            self._latest_summary = self._build_summary()
            self._lifecycle_state = "meeting_ended"
            self._transition_runtime("manual_override")
            self._last_error = None
            return True
        return False

    def _direct_address_candidate(
        self,
        text: str,
        utterance_id: str,
    ) -> AgentCandidateIntervention | None:
        if not _is_addressed_to_erica(text):
            return None
        allowed = self._mode in {"assistant", "facilitator", "qa"}
        cooldown_ok = self._cooldown_allows_speech()
        speak_allowed = allowed and cooldown_ok
        if not allowed:
            reason = f"mode {self._mode} stores direct-address responses without speaking"
        elif not cooldown_ok:
            reason = "cooldown prevents immediate response"
        else:
            reason = "direct address detected and mode allows response"
        return AgentCandidateIntervention(
            candidate_id=uuid.uuid4().hex[:12],
            type="direct_answer",
            text=self._direct_answer_text(text, source_utterance_id=utterance_id),
            score=0.9,
            speak_allowed=speak_allowed,
            reason=reason,
            source_utterance_id=utterance_id,
            created_at_ms=now_ms(),
        )

    def _direct_answer_text(self, text: str, *, source_utterance_id: str) -> str:
        context = DirectAnswerContext(
            question=_clean_erica_address(text),
            current_topic=self._current_topic.topic if self._current_topic else None,
            recent_utterances=[
                item.text
                for item in self._recent_utterances
                if item.utterance_id != source_utterance_id
            ],
            requirements=[
                item
                for item in self._requirements
                if item.source_utterance_id != source_utterance_id
            ],
            open_questions=[
                item
                for item in self._open_questions
                if item.source_utterance_id != source_utterance_id
            ],
            decisions=[
                item for item in self._decisions if item.source_utterance_id != source_utterance_id
            ],
        )
        llm_answer = self._llm_direct_answer(context)
        if llm_answer:
            return llm_answer
        return self._reasoner.answer_direct_question(context)

    def _llm_direct_answer(self, context: DirectAnswerContext) -> str | None:
        if self._llm_client is None:
            return None
        answer_direct_question = getattr(self._llm_client, "answer_direct_question", None)
        if not callable(answer_direct_question):
            return None
        try:
            started_at_ms = now_ms()
            answer = str(answer_direct_question(context)).strip()
        except Exception as exc:
            self._last_error = f"direct answer failed: {type(exc).__name__}: {exc}"
            self._append_llm_call_trace(
                operation="direct_answer",
                started_at_ms=started_at_ms,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                input_preview=context.question,
            )
            return None
        if not answer:
            self._append_llm_call_trace(
                operation="direct_answer",
                started_at_ms=started_at_ms,
                success=False,
                error="empty response",
                input_preview=context.question,
            )
            return None
        self._append_llm_call_trace(
            operation="direct_answer",
            started_at_ms=started_at_ms,
            success=True,
            input_preview=context.question,
            output_preview=answer,
        )
        self._last_error = None
        return answer

    def _requirement_candidate(
        self,
        text: str,
        utterance_id: str,
        *,
        event_ms: float,
    ) -> AgentCandidateIntervention | None:
        if self._mode not in {"passive", "assistant", "facilitator", "scribe"}:
            return None
        if not _looks_like_requirement(text):
            return None
        llm_candidate = self._llm_candidate(text, utterance_id, event_ms=event_ms)
        if self._llm_client is not None:
            return llm_candidate
        topic = _short_requirement_topic(text)
        silence_ms = self._silence_since_last_human_ms(event_ms)
        can_auto_speak = self._can_auto_speak_proactively(silence_ms=silence_ms)
        if can_auto_speak:
            reason = "facilitator mode and silence window allow proactive clarification"
        elif (
            self._mode == "facilitator"
            and self._settings.aggressiveness >= self._config.proactive_min_aggressiveness
        ):
            reason = "facilitator mode is waiting for a safe silence window"
        else:
            reason = "requirement-like statement detected; stored silently for review"
        return AgentCandidateIntervention(
            candidate_id=uuid.uuid4().hex[:12],
            type="clarifying_question",
            text=f"What acceptance criteria should we use for: {topic}?",
            score=0.62,
            speak_allowed=can_auto_speak,
            reason=reason,
            source_utterance_id=utterance_id,
            created_at_ms=now_ms(),
        )

    def _llm_candidate(
        self,
        text: str,
        utterance_id: str,
        *,
        event_ms: float,
    ) -> AgentCandidateIntervention | None:
        if self._llm_client is None:
            return None
        silence_ms = self._silence_since_last_human_ms(event_ms)
        cooldown_allows_speech = self._cooldown_allows_speech()
        can_auto_speak = self._can_auto_speak_proactively(silence_ms=silence_ms)
        started_at_ms = now_ms()
        try:
            decision = self._llm_client.decide(
                ReasoningContext(
                    mode=self._mode,
                    runtime_state=self._runtime_state,
                    utterance=text,
                    context_summaries=list(self._context_summaries),
                    current_topic=self._current_topic.topic if self._current_topic else None,
                    recent_utterances=[item.text for item in self._recent_utterances],
                    requirements=list(self._requirements),
                    open_questions=list(self._open_questions),
                    decisions=list(self._decisions),
                    cooldown_allows_speech=cooldown_allows_speech,
                    can_auto_speak=can_auto_speak,
                )
            )
        except Exception as exc:
            self._last_error = f"reasoning failed: {type(exc).__name__}: {exc}"
            self._append_llm_call_trace(
                operation="reasoning",
                started_at_ms=started_at_ms,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                input_preview=text,
            )
            self._append_reasoning_trace(
                utterance_id=utterance_id,
                can_auto_speak=can_auto_speak,
                cooldown_allows_speech=cooldown_allows_speech,
                error=self._last_error,
            )
            return None
        self._append_llm_call_trace(
            operation="reasoning",
            started_at_ms=started_at_ms,
            success=True,
            input_preview=text,
            output_preview=decision.reason,
        )
        self._append_reasoning_trace(
            utterance_id=utterance_id,
            can_auto_speak=can_auto_speak,
            cooldown_allows_speech=cooldown_allows_speech,
            decision=decision,
        )
        if decision.requirement_refinement is not None:
            self._apply_requirement_refinement(
                decision.requirement_refinement,
                source_utterance_id=utterance_id,
            )
        if decision.action == "capture_decision" and decision.text:
            self._append_or_merge_decision(
                DecisionRecord(
                    decision_id=uuid.uuid4().hex[:12],
                    text=_normalize_record_text(decision.text),
                    source_utterance_id=utterance_id,
                    source_utterance_ids=[utterance_id],
                    speaker="llm",
                    created_at_ms=now_ms(),
                )
            )
            self._last_error = None
            if decision.candidate_type is None:
                return None
        if decision.action not in {
            "draft_candidate",
            "speak_now",
            "ask_clarifying_question",
            "summarize",
            "capture_decision",
            "suggest_mode_change",
        }:
            self._last_error = None
            return None
        if decision.candidate_type is None or not decision.text:
            self._last_error = "reasoning failed: candidate decision missing type or text"
            return None
        if decision.action == "suggest_mode_change" and (
            decision.candidate_type != "mode_change" or decision.suggested_mode is None
        ):
            self._last_error = "reasoning failed: mode change decision missing suggested mode"
            return None
        speak_allowed = decision.action == "speak_now" and can_auto_speak
        return AgentCandidateIntervention(
            candidate_id=uuid.uuid4().hex[:12],
            type=decision.candidate_type,
            text=decision.text,
            score=decision.score,
            speak_allowed=speak_allowed,
            reason=decision.reason,
            source_utterance_id=utterance_id,
            suggested_mode=decision.suggested_mode,
            created_at_ms=now_ms(),
        )

    def _append_reasoning_trace(
        self,
        *,
        utterance_id: str,
        can_auto_speak: bool,
        cooldown_allows_speech: bool,
        decision: AgentReasoningDecision | None = None,
        error: str | None = None,
    ) -> None:
        self._reasoning_traces.append(
            AgentReasoningTrace(
                trace_id=uuid.uuid4().hex[:12],
                utterance_id=utterance_id,
                action=decision.action if decision is not None else None,
                candidate_type=decision.candidate_type if decision is not None else None,
                score=decision.score if decision is not None else None,
                reason=decision.reason if decision is not None else None,
                suggested_mode=decision.suggested_mode if decision is not None else None,
                error=error,
                created_at_ms=now_ms(),
                mode=self._mode,
                runtime_state=self._runtime_state,
                can_auto_speak=can_auto_speak,
                cooldown_allows_speech=cooldown_allows_speech,
                context_summary_count=len(self._context_summaries),
                recent_utterance_count=len(self._recent_utterances),
            )
        )

    def _append_llm_call_trace(
        self,
        *,
        operation: Literal["reasoning", "direct_answer", "context_summary"],
        started_at_ms: float,
        success: bool,
        error: str | None = None,
        input_preview: str | None = None,
        output_preview: str | None = None,
    ) -> None:
        self._llm_call_traces.append(
            AgentLLMCallTrace(
                trace_id=uuid.uuid4().hex[:12],
                operation=operation,
                provider=_provider_name(self._llm_client),
                success=success,
                latency_ms=max(0.0, now_ms() - started_at_ms),
                error=_preview_text(error),
                input_preview=_preview_text(input_preview),
                output_preview=_preview_text(output_preview),
                created_at_ms=now_ms(),
            )
        )

    def _extract_memory_records(
        self,
        text: str,
        *,
        utterance_id: str,
        speaker: str,
        created_at_ms: float,
    ) -> None:
        if _looks_like_requirement(text):
            requirement_fields = _requirement_fields(text)
            acceptance_question = (
                "What acceptance criteria should we use for: "
                f"{_short_requirement_topic(_requirement_semantic_text(text))}?"
            )
            requirement = RequirementRecord(
                requirement_id=uuid.uuid4().hex[:12],
                text=_requirement_record_text(text),
                source_utterance_id=utterance_id,
                source_utterance_ids=[utterance_id],
                speaker=speaker,
                created_at_ms=created_at_ms,
                actor=requirement_fields.actor,
                goal=requirement_fields.goal,
                behavior=requirement_fields.behavior,
                constraints=list(requirement_fields.constraints),
                    priority=requirement_fields.priority,
                    owner=requirement_fields.owner,
                    status=requirement_fields.status,
                    acceptance_criteria=list(requirement_fields.acceptance_criteria),
                    open_questions=[acceptance_question],
                )
            self._append_or_merge_requirement(requirement)
        if _looks_like_question(text):
            self._append_or_merge_question(
                OpenQuestionRecord(
                    question_id=uuid.uuid4().hex[:12],
                    text=_normalize_record_text(text),
                    source_utterance_id=utterance_id,
                    source_utterance_ids=[utterance_id],
                    speaker=speaker,
                    created_at_ms=created_at_ms,
                    related_requirement_ids=self._related_requirement_ids_for_question(text),
                )
            )
        decision_text = _decision_text(text)
        if decision_text is not None:
            self._append_or_merge_decision(
                DecisionRecord(
                    decision_id=uuid.uuid4().hex[:12],
                    text=decision_text,
                    source_utterance_id=utterance_id,
                    source_utterance_ids=[utterance_id],
                    speaker=speaker,
                    created_at_ms=created_at_ms,
                )
            )
        action_item_text = _action_item_text(text) if decision_text is None else None
        if action_item_text is not None:
            self._append_or_merge_action_item(
                ActionItemRecord(
                    action_item_id=uuid.uuid4().hex[:12],
                    text=action_item_text,
                    source_utterance_id=utterance_id,
                    source_utterance_ids=[utterance_id],
                    speaker=speaker,
                    created_at_ms=created_at_ms,
                    owner=_action_item_owner(action_item_text),
                )
            )
        risk_text = _risk_text(text)
        if risk_text is not None:
            self._append_or_merge_risk(
                RiskRecord(
                    risk_id=uuid.uuid4().hex[:12],
                    text=risk_text,
                    source_utterance_id=utterance_id,
                    source_utterance_ids=[utterance_id],
                    speaker=speaker,
                    created_at_ms=created_at_ms,
                    severity=_risk_severity(risk_text),
                )
            )
        parked_topic_text = _parked_topic_text(text)
        if parked_topic_text is not None:
            self._append_or_merge_parked_topic(
                ParkedTopicRecord(
                    parked_topic_id=uuid.uuid4().hex[:12],
                    text=parked_topic_text,
                    source_utterance_id=utterance_id,
                    source_utterance_ids=[utterance_id],
                    speaker=speaker,
                    created_at_ms=created_at_ms,
                )
            )

    def _update_memory_lifecycle(self, text: str, *, source_utterance_id: str) -> None:
        self._mark_related_questions_answered(text, source_utterance_id=source_utterance_id)
        self._mark_confirmed_decision(text, source_utterance_id=source_utterance_id)
        self._mark_completed_action_item(text, source_utterance_id=source_utterance_id)

    def _speak_candidate(
        self,
        candidate: AgentCandidateIntervention,
        *,
        speaker: SpeechEnqueuer,
        interrupt: bool,
    ) -> None:
        try:
            self._transition_runtime("thinking")
            job = speaker.enqueue(candidate.text, interrupt=interrupt)
            self._active_speech_job_id = getattr(job, "job_id", None)
            self._last_speech_job_id = self._active_speech_job_id
            self._transition_runtime("speaking")
            self._last_error = None
        except RuntimeError as exc:
            self._last_error = str(exc)
            self._transition_runtime("candidate_intervention")

    def _cooldown_allows_speech(self) -> bool:
        if self._last_agent_speech_at_ms is None:
            return True
        return now_ms() - self._last_agent_speech_at_ms >= self._settings.direct_answer_cooldown_ms

    def _candidate_waits_for_turn(self, candidate: AgentCandidateIntervention) -> bool:
        return (
            self._mode == "facilitator"
            and candidate.type == "clarifying_question"
            and self._settings.aggressiveness >= self._config.proactive_min_aggressiveness
            and self._cooldown_allows_speech()
        )

    def _next_auto_speak_candidate(self, event_ms: float) -> AgentCandidateIntervention | None:
        silence_ms = self._silence_since_last_human_ms(event_ms)
        if not self._can_auto_speak_proactively(silence_ms=silence_ms):
            if self._runtime_state == "candidate_intervention" and self._candidate_interventions:
                self._transition_runtime("waiting_for_turn")
            return None
        for candidate in reversed(self._candidate_interventions):
            if candidate.type == "clarifying_question":
                candidate.speak_allowed = True
                candidate.reason = (
                    "facilitator mode and silence window allow proactive clarification"
                )
                return candidate
        return None

    def _can_auto_speak_proactively(self, *, silence_ms: float | None) -> bool:
        return (
            self._mode == "facilitator"
            and self._lifecycle_state == "in_meeting"
            and self._readiness.can_auto_speak
            and self._runtime_state not in {"speaking", "thinking", "interrupted"}
            and self._settings.aggressiveness >= self._config.proactive_min_aggressiveness
            and self._cooldown_allows_speech()
            and silence_ms is not None
            and silence_ms >= self._settings.proactive_min_silence_ms
        )

    def _silence_since_last_human_ms(self, event_ms: float) -> float | None:
        if self._last_human_speech_at_ms is None:
            return None
        return max(0.0, event_ms - self._last_human_speech_at_ms)

    def _transition_runtime(self, state: AgentRuntimeState) -> None:
        if self._runtime_state == state:
            return
        self._runtime_state = state
        self._last_state_change_at_ms = now_ms()

    def _refresh_runtime_state(self) -> None:
        if self._runtime_state == "cooldown" and self._cooldown_allows_speech():
            self._transition_runtime("idle_listening")

    def _update_current_topic(
        self,
        text: str,
        *,
        utterance_id: str,
        updated_at_ms: float,
    ) -> None:
        topic = _current_topic_from_utterance(text)
        if topic is None:
            return
        self._current_topic = CurrentTopicState(
            topic=topic,
            source_utterance_id=utterance_id,
            updated_at_ms=updated_at_ms,
        )

    def _maybe_update_context_summary(self) -> None:
        utterance_count = len(self._recent_utterances)
        interval = self._config.context_summary_utterance_interval
        if interval <= 0:
            return
        if utterance_count - self._last_context_summary_utterance_count < interval:
            return
        window = list(self._recent_utterances)[-interval:]
        if not window:
            return
        summary = self._context_summary_from_window(window)
        self._context_summaries.append(summary)
        self._last_context_summary_utterance_count = utterance_count

    def _context_summary_from_window(
        self,
        window: list[AgentUtterance],
    ) -> MeetingContextSummary:
        fallback = _context_summary_from_window(
            window,
            requirements=list(self._requirements),
            open_questions=list(self._open_questions),
            decisions=list(self._decisions),
            action_items=list(self._action_items),
            risks=list(self._risks),
            parked_topics=list(self._parked_topics),
        )
        llm_text = self._llm_context_summary(window)
        if not llm_text:
            return fallback
        return fallback.model_copy(update={"text": llm_text})

    def _llm_context_summary(self, window: list[AgentUtterance]) -> str | None:
        if self._llm_client is None:
            return None
        summarize_context = getattr(self._llm_client, "summarize_context", None)
        if not callable(summarize_context):
            return None
        try:
            started_at_ms = now_ms()
            summary = str(
                summarize_context(
                    ContextSummaryRequest(
                        utterances=[f"{item.speaker}: {item.text}" for item in window],
                        requirements=list(self._requirements),
                        open_questions=list(self._open_questions),
                        decisions=list(self._decisions),
                        action_items=list(self._action_items),
                        risks=list(self._risks),
                        parked_topics=list(self._parked_topics),
                    )
                )
            ).strip()
        except Exception as exc:
            self._last_error = f"context summary failed: {type(exc).__name__}: {exc}"
            self._append_llm_call_trace(
                operation="context_summary",
                started_at_ms=started_at_ms,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                input_preview=f"{len(window)} utterances",
            )
            return None
        if not summary:
            self._append_llm_call_trace(
                operation="context_summary",
                started_at_ms=started_at_ms,
                success=False,
                error="empty response",
                input_preview=f"{len(window)} utterances",
            )
            return None
        self._last_error = None
        summary_text = _truncate_summary_text(summary)
        self._append_llm_call_trace(
            operation="context_summary",
            started_at_ms=started_at_ms,
            success=True,
            input_preview=f"{len(window)} utterances",
            output_preview=summary_text,
        )
        return summary_text

    def _build_summary(self) -> MeetingSummaryArtifact:
        requirements = list(self._requirements)
        open_questions = list(self._open_questions)
        decisions = list(self._decisions)
        action_items = list(self._action_items)
        risks = list(self._risks)
        parked_topics = list(self._parked_topics)
        context_summaries = list(self._context_summaries)
        candidates = list(self._candidate_interventions)
        generated_at_ms = now_ms()
        markdown = _summary_markdown(
            meeting_id=self._meeting_id,
            meeting_url=self._meeting_url,
            requirements=requirements,
            open_questions=open_questions,
            decisions=decisions,
            action_items=action_items,
            risks=risks,
            parked_topics=parked_topics,
            context_summaries=context_summaries,
            current_topic=self._current_topic,
            candidates=candidates,
        )
        summary = MeetingSummaryArtifact(
            meeting_id=self._meeting_id,
            meeting_url=self._meeting_url,
            generated_at_ms=generated_at_ms,
            utterance_count=len(self._recent_utterances),
            participant_count=len(self._participants),
            requirements=requirements,
            open_questions=open_questions,
            decisions=decisions,
            action_items=action_items,
            risks=risks,
            parked_topics=parked_topics,
            context_summaries=context_summaries,
            current_topic=self._current_topic,
            candidate_interventions=candidates,
            markdown=markdown,
        )
        return self._persist_summary(summary)

    def _persist_summary(self, summary: MeetingSummaryArtifact) -> MeetingSummaryArtifact:
        if self._summary_dir is None:
            return summary
        self._summary_dir.mkdir(parents=True, exist_ok=True)
        stem = _summary_file_stem(summary.meeting_id, summary.generated_at_ms)
        json_path = self._summary_dir / f"{stem}.json"
        markdown_path = self._summary_dir / f"{stem}.md"
        markdown_path.write_text(summary.markdown, encoding="utf-8")
        persisted = summary.model_copy(
            update={
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
            }
        )
        json_path.write_text(persisted.model_dump_json(indent=2), encoding="utf-8")
        return persisted

    def _append_or_merge_requirement(self, record: RequirementRecord) -> RequirementRecord:
        existing = _find_by_record_key(self._requirements, record.text)
        if existing is None:
            self._requirements.append(record)
            return record
        _merge_sources(existing, record.source_utterance_id)
        for question in record.open_questions:
            if question not in existing.open_questions:
                existing.open_questions.append(question)
        _merge_optional_requirement_fields(existing, record)
        return existing

    def _apply_requirement_refinement(
        self,
        refinement: RequirementRefinement,
        *,
        source_utterance_id: str,
    ) -> RequirementRecord | None:
        target = self._target_requirement_for_refinement(refinement)
        if target is None:
            return None
        _merge_sources(target, source_utterance_id)
        if refinement.text:
            target.text = _normalize_record_text(refinement.text)
        if refinement.actor:
            target.actor = _normalize_record_text(refinement.actor)
        if refinement.goal:
            target.goal = _normalize_record_text(refinement.goal)
        if refinement.behavior:
            target.behavior = _normalize_record_text(refinement.behavior)
        if refinement.owner:
            target.owner = _normalize_record_text(refinement.owner)
        if refinement.priority != "unknown":
            target.priority = refinement.priority
        if refinement.status is not None:
            target.status = refinement.status
        for constraint in refinement.constraints:
            normalized = _normalize_record_text(constraint).rstrip(".")
            if normalized and normalized not in target.constraints:
                target.constraints.append(normalized)
        for criterion in refinement.acceptance_criteria:
            normalized = _normalize_record_text(criterion).rstrip(".")
            if normalized and normalized not in target.acceptance_criteria:
                target.acceptance_criteria.append(normalized)
        for question in refinement.open_questions:
            normalized = _normalize_record_text(question).rstrip(".")
            if normalized and normalized not in target.open_questions:
                target.open_questions.append(normalized)
        return target

    def _target_requirement_for_refinement(
        self,
        refinement: RequirementRefinement,
    ) -> RequirementRecord | None:
        if refinement.target_requirement_id:
            for requirement in self._requirements:
                if requirement.requirement_id == refinement.target_requirement_id:
                    return requirement
        if refinement.text:
            existing = _find_by_record_key(self._requirements, refinement.text)
            if existing is not None:
                return existing
        return self._requirements[-1] if self._requirements else None

    def _append_or_merge_question(self, record: OpenQuestionRecord) -> OpenQuestionRecord:
        existing = _find_by_record_key(self._open_questions, record.text)
        if existing is None:
            self._open_questions.append(record)
            return record
        _merge_sources(existing, record.source_utterance_id)
        _merge_related_requirement_ids(existing, record.related_requirement_ids)
        return existing

    def _related_requirement_ids_for_question(self, text: str) -> list[str]:
        question_terms = _link_terms(text)
        related: list[str] = []
        for requirement in reversed(self._requirements):
            if _question_links_to_requirement(question_terms, requirement):
                related.append(requirement.requirement_id)
            if len(related) >= 3:
                break
        return list(reversed(related))

    def _append_or_merge_decision(self, record: DecisionRecord) -> None:
        existing = _find_by_record_key(self._decisions, record.text)
        if existing is None:
            self._decisions.append(record)
            return
        _merge_sources(existing, record.source_utterance_id)
        if record.confirmed:
            existing.confirmed = True

    def _append_or_merge_action_item(self, record: ActionItemRecord) -> None:
        existing = _find_by_record_key(self._action_items, record.text)
        if existing is None:
            self._action_items.append(record)
            return
        _merge_sources(existing, record.source_utterance_id)
        if existing.owner is None and record.owner is not None:
            existing.owner = record.owner
        if record.completed:
            existing.completed = True

    def _append_or_merge_risk(self, record: RiskRecord) -> None:
        existing = _find_by_record_key(self._risks, record.text)
        if existing is None:
            self._risks.append(record)
            return
        _merge_sources(existing, record.source_utterance_id)
        existing.severity = _max_risk_severity(existing.severity, record.severity)

    def _append_or_merge_parked_topic(self, record: ParkedTopicRecord) -> None:
        existing = _find_by_record_key(self._parked_topics, record.text)
        if existing is None:
            self._parked_topics.append(record)
            return
        _merge_sources(existing, record.source_utterance_id)

    def _mark_related_questions_answered(self, text: str, *, source_utterance_id: str) -> None:
        if _looks_like_question(text):
            return
        answer_terms = _link_terms(text)
        if not answer_terms and not _explicit_answer_reference(text):
            return
        for question in self._open_questions:
            if question.answered:
                continue
            if _answer_links_to_question(text, answer_terms, question):
                question.answered = True
                _merge_sources(question, source_utterance_id)

    def _mark_confirmed_decision(self, text: str, *, source_utterance_id: str) -> None:
        decision_text = _confirmed_decision_text(text)
        if decision_text is None:
            return
        existing = _find_by_record_key(self._decisions, decision_text)
        if existing is None:
            return
        existing.confirmed = True
        _merge_sources(existing, source_utterance_id)

    def _mark_completed_action_item(self, text: str, *, source_utterance_id: str) -> None:
        action_text = _completed_action_item_text(text)
        if action_text is None:
            return
        existing = _find_by_record_key(self._action_items, action_text)
        if existing is None:
            return
        existing.completed = True
        _merge_sources(existing, source_utterance_id)


def _is_addressed_to_erica(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.search(r"\b(?:hey\s+)?erica\b", normalized)
        or re.search(r"\bask\s+erica\b", normalized)
        or re.search(r"\bcan\s+erica\b", normalized)
    )


def _clean_erica_address(text: str) -> str:
    cleaned = re.sub(r"^\s*(?:hey\s+)?erica[:,]?\s*", "", text, flags=re.IGNORECASE).strip()
    return cleaned


def _explicit_erica_command(text: str) -> tuple[str, AgentParticipationMode | None] | None:
    if not _is_addressed_to_erica(text):
        return None
    command = _clean_erica_address(text).strip().lower().rstrip(".!?")
    if not command:
        return None
    if re.match(
        r"^(?:please\s+)?(?:end|finish|close|stop)\s+(?:the\s+)?meeting$",
        command,
    ):
        return ("end_meeting", None)
    match = re.match(
        r"^(?:please\s+)?(?:switch|change|set|go)\s+(?:to\s+)?"
        r"(?P<mode>off|passive|assistant|facilitator|qa|q&a|scribe)\s*(?:mode)?$",
        command,
    )
    if match is None:
        return None
    mode_map: dict[str, AgentParticipationMode] = {
        "off": "off",
        "passive": "passive",
        "assistant": "assistant",
        "facilitator": "facilitator",
        "qa": "qa",
        "q&a": "qa",
        "scribe": "scribe",
    }
    return ("mode", mode_map[match.group("mode")])


def _looks_like_requirement(text: str) -> bool:
    normalized = text.strip().lower()
    if "?" in normalized:
        return False
    patterns = [
        r"\bwe\s+need\b",
        r"\bwe\s+should\b",
        r"\bwe\s+must\b",
        r"\busers?\s+(?:can|should|must|need)\b",
        r"\bthe\s+system\s+(?:should|must|needs?\s+to)\b",
        r"\brequirement\b",
    ]
    return any(re.search(pattern, normalized) for pattern in patterns)


def _short_requirement_topic(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    cleaned = re.sub(
        r"^(?:we|users?|the system)\s+(?:need|needs to|should|must|can)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.rstrip(".")
    if len(cleaned) > 96:
        cleaned = f"{cleaned[:93].rstrip()}..."
    return cleaned or "that requirement"


def _requirement_fields(text: str) -> RequirementFields:
    cleaned = _normalize_record_text(text).rstrip(".")
    normalized = cleaned.lower()
    semantic_text = _requirement_semantic_text(cleaned)
    actor, behavior = _requirement_actor_and_behavior(semantic_text)
    return RequirementFields(
        actor=actor,
        goal=_requirement_goal(semantic_text),
        behavior=behavior,
        constraints=tuple(_requirement_constraints(behavior or semantic_text)),
        priority=_requirement_priority(normalized),
        owner=_requirement_owner(cleaned),
        status="clarifying",
        acceptance_criteria=tuple(_requirement_acceptance_criteria(cleaned)),
    )


def _requirement_semantic_text(text: str) -> str:
    value = re.sub(r"\bpriority[:\s-]+[^.]+\.?", "", text, flags=re.IGNORECASE)
    value = re.sub(
        r"\bowner[:\s-]+[A-Za-z][A-Za-z\s]{0,40}\b\.?",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:acceptance criteria|definition of done|done when)[:\s-]+[^.]+\.?",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return _normalize_record_text(value).rstrip(".")


def _requirement_record_text(text: str) -> str:
    semantic = _requirement_semantic_text(text)
    if text.strip().endswith(".") and not semantic.endswith("."):
        return f"{semantic}."
    return semantic


def _requirement_actor_and_behavior(text: str) -> tuple[str | None, str | None]:
    cleaned = _normalize_record_text(text).rstrip(".")
    patterns = [
        r"^(?P<actor>users?|admins?|customers?|operators?|participants?|hosts?|guests?)\s+"
        r"(?P<modal>can|should|must|need(?:s)?\s+to)\s+(?P<behavior>.+)$",
        r"^(?P<actor>the\s+system|system|app|application|backend|extension|erica)\s+"
        r"(?P<modal>can|should|must|need(?:s)?\s+to)\s+(?P<behavior>.+)$",
        r"^we\s+(?:need|should|must)\s+(?P<actor>users?|admins?|customers?|operators?)\s+"
        r"to\s+(?P<behavior>.+)$",
        r"^we\s+(?:need|should|must)\s+(?P<behavior>.+)$",
        r"^requirement[:\s-]+(?P<behavior>.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned, flags=re.IGNORECASE)
        if match is None:
            continue
        actor = match.groupdict().get("actor")
        behavior = match.groupdict().get("behavior")
        if behavior:
            return _normalize_optional(actor), _strip_requirement_goal(behavior)
    return None, None


def _requirement_goal(text: str) -> str | None:
    match = re.search(r"\bso\s+that\s+(.+)$|\bso\s+(.+)$", text, flags=re.IGNORECASE)
    if match is None:
        return None
    goal = next(group for group in match.groups() if group)
    return _normalize_record_text(goal.rstrip("."))


def _strip_requirement_goal(text: str) -> str:
    value = re.split(r"\bso\s+that\b|\bso\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return _normalize_record_text(value.rstrip("."))


def _requirement_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    patterns = [
        r"\b(before\s+[^,.]+)",
        r"\b(after\s+[^,.]+)",
        r"\bwithin\s+([^,.]+)",
        r"\bonly\s+if\s+([^,.]+)",
        r"\bunless\s+([^,.]+)",
        r"\bwithout\s+([^,.]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _normalize_record_text(match.group(1).rstrip("."))
            if value and value not in constraints:
                constraints.append(value)
    return constraints


def _requirement_priority(normalized_text: str) -> RequirementPriority:
    if any(term in normalized_text for term in ["p0", "critical", "must have", "must-have"]):
        return "high"
    if any(term in normalized_text for term in ["p1", "important", "should have", "should-have"]):
        return "medium"
    if any(term in normalized_text for term in ["p2", "nice to have", "nice-to-have"]):
        return "low"
    return "unknown"


def _requirement_owner(text: str) -> str | None:
    match = re.search(r"\bowner[:\s-]+([A-Za-z][A-Za-z\s]{0,40})\b", text, re.IGNORECASE)
    if match is None:
        return None
    return _normalize_record_text(match.group(1))


def _requirement_acceptance_criteria(text: str) -> list[str]:
    cleaned = _normalize_record_text(text).rstrip(".")
    patterns = [
        r"\bacceptance criteria[:\s-]+(.+?)(?=\.\s*(?:Priority|Owner)\b|$)",
        r"\bdefinition of done\s+(?:is|:)\s+(.+?)(?=\.\s*(?:Priority|Owner)\b|$)",
        r"\bdone when\s+(.+?)(?=\.\s*(?:Priority|Owner)\b|$)",
    ]
    criteria: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned, flags=re.IGNORECASE):
            for criterion in _split_acceptance_criteria(match.group(1)):
                if criterion not in criteria:
                    criteria.append(criterion)
    return criteria


def _split_acceptance_criteria(text: str) -> list[str]:
    value = re.sub(r"\b(?:and|or)\b", ";", text, flags=re.IGNORECASE)
    parts = re.split(r"\s*(?:;|\||,)\s*", value)
    return [_normalize_record_text(part).rstrip(".") for part in parts if part.strip()]


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_record_text(value)
    return normalized or None


def _looks_like_question(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized.endswith("?") or "?" in normalized:
        return True
    return bool(
        re.match(
            r"^(?:who|what|when|where|why|how|should|could|can|do|does|is|are)\b",
            normalized,
        )
    )


def _decision_text(text: str) -> str | None:
    normalized = text.strip().lower()
    patterns = [
        r"^(?:we\s+)?decided\s+(?:that\s+)?(.+)$",
        r"^(?:the\s+)?decision\s+is\s+(?:to\s+)?(.+)$",
        r"^let'?s\s+go\s+with\s+(.+)$",
        r"^we\s+will\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match is None:
            continue
        decision = match.group(1).strip().rstrip(".")
        decision = re.sub(r"^to\s+", "", decision)
        if decision:
            return decision
    return None


def _confirmed_decision_text(text: str) -> str | None:
    normalized = text.strip().lower()
    patterns = [
        r"^(?:confirmed|confirming|decision confirmed)[:\s-]+(.+)$",
        r"^(?:we\s+)?confirmed\s+(?:that\s+)?(.+)$",
        r"^(?:yes,\s+)?(?:that|this)\s+decision\s+is\s+confirmed[:\s-]*(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match is None:
            continue
        value = match.group(1).strip().rstrip(".")
        value = re.sub(r"^to\s+", "", value)
        if value:
            return value
    return None


def _action_item_text(text: str) -> str | None:
    cleaned = " ".join(text.strip().split()).rstrip(".")
    normalized = cleaned.lower()
    patterns = [
        r"^(?:action item|todo|to do)[:\s-]+(.+)$",
        r"^(?:i|we|[a-z][a-z\s]{0,40})\s+will\s+(.+)$",
        r"^(?:i|we|[a-z][a-z\s]{0,40})\s+need\s+to\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match is None:
            continue
        value = match.group(1).strip()
        if value and not _looks_like_requirement(cleaned):
            return value
    return None


def _completed_action_item_text(text: str) -> str | None:
    normalized = _normalize_record_text(text).rstrip(".").lower()
    patterns = [
        r"^(?:completed|done|finished)[:\s-]+(.+)$",
        r"^(?:action item|todo|to do)\s+(?:completed|done|finished)[:\s-]+(.+)$",
        r"^(?:we|i|[a-z][a-z\s]{0,40})\s+(?:completed|finished)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match is None:
            continue
        value = match.group(1).strip()
        if value:
            return value
    return None


def _action_item_owner(text: str) -> str | None:
    match = re.match(r"^([a-z][a-z\s]{1,40})\s+(?:will|needs?\s+to)\s+", text.lower())
    if match is None:
        return None
    owner = match.group(1).strip()
    if owner in {"i", "we", "users", "user", "the system"}:
        return None
    return owner


def _risk_text(text: str) -> str | None:
    cleaned = " ".join(text.strip().split()).rstrip(".")
    normalized = cleaned.lower()
    patterns = [
        r"^(?:risk|concern|blocker)[:\s-]+(.+)$",
        r"^(?:the\s+)?risk\s+is\s+(?:that\s+)?(.+)$",
        r"^(?:i'?m\s+)?concerned\s+(?:that\s+)?(.+)$",
        r"^we\s+(?:might|may|could)\s+(?:not\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match is None:
            continue
        value = match.group(1).strip()
        if value:
            return value
    return None


def _risk_severity(text: str) -> str:
    normalized = text.lower()
    high_terms = ["blocker", "blocked", "critical", "security", "data loss"]
    if any(word in normalized for word in high_terms):
        return "high"
    if any(word in normalized for word in ["delay", "risk", "concern", "unclear"]):
        return "medium"
    return "unknown"


def _parked_topic_text(text: str) -> str | None:
    cleaned = " ".join(text.strip().split()).rstrip(".")
    normalized = cleaned.lower()
    patterns = [
        r"^(?:parking lot|parked topic|follow[-\s]?up)[:\s-]+(.+)$",
        r"^(?:let'?s\s+)?park\s+(?:that|this|it|the\s+topic)?\s*(?:for\s+later)?[:\s-]*(.+)$",
        r"^(?:put|add)\s+(.+?)\s+(?:in|to)\s+(?:the\s+)?parking\s+lot$",
        r"^(?:put|add)\s+(?:that|this|it)\s+(?:in|to)\s+(?:the\s+)?parking\s+lot[:\s-]+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match is None:
            continue
        value = match.group(1).strip()
        if value:
            return value
    return None


def _current_topic_from_utterance(text: str) -> str | None:
    cleaned = _normalize_record_text(text).rstrip(".")
    normalized = cleaned.lower()
    explicit_patterns = [
        r"^(?:next|new)\s+topic\s+(?:is|will\s+be|:)\s+(.+)$",
        r"^(?:the\s+)?current\s+topic\s+(?:is|:)\s+(.+)$",
        r"^(?:let'?s|we\s+should)\s+(?:move|switch|go)\s+(?:on\s+)?to\s+(.+)$",
    ]
    for pattern in explicit_patterns:
        match = re.match(pattern, normalized)
        if match is None:
            continue
        topic = _short_topic(match.group(1))
        return topic or None
    if _looks_like_requirement(cleaned):
        fields = _requirement_fields(cleaned)
        requirement_topic = fields.behavior or _short_requirement_topic(
            _requirement_semantic_text(cleaned)
        )
        return _short_topic(requirement_topic)
    return None


def _normalize_record_text(text: str) -> str:
    return " ".join(text.strip().split())


def _summary_markdown(
    *,
    meeting_id: str | None,
    meeting_url: str | None,
    requirements: list[RequirementRecord],
    open_questions: list[OpenQuestionRecord],
    decisions: list[DecisionRecord],
    action_items: list[ActionItemRecord],
    risks: list[RiskRecord],
    parked_topics: list[ParkedTopicRecord],
    context_summaries: list[MeetingContextSummary],
    current_topic: CurrentTopicState | None,
    candidates: list[AgentCandidateIntervention],
) -> str:
    lines = ["# Erica Meeting Summary", ""]
    if meeting_id is not None:
        lines.append(f"- Meeting ID: `{meeting_id}`")
    if meeting_url is not None:
        lines.append(f"- Meeting URL: {meeting_url}")
    if meeting_id is not None or meeting_url is not None:
        lines.append("")
    if current_topic is not None:
        lines.extend(["## Current Topic", "", f"- {current_topic.topic}", ""])

    lines.extend(_summary_section("Requirements", _requirement_summary_lines(requirements)))
    lines.extend(
        _summary_section(
            "Open Questions",
            _open_question_summary_lines(open_questions, requirements=requirements),
        )
    )
    lines.extend(_summary_section("Decisions", _decision_summary_lines(decisions)))
    lines.extend(_summary_section("Action Items", _action_item_summary_lines(action_items)))
    lines.extend(_summary_section("Risks", [item.text for item in risks]))
    lines.extend(_summary_section("Parked Topics", [item.text for item in parked_topics]))
    lines.extend(_summary_section("Context Checkpoints", [item.text for item in context_summaries]))
    lines.extend(_summary_section("Candidate Interventions", [item.text for item in candidates]))
    return "\n".join(lines).rstrip() + "\n"


def _summary_section(title: str, items: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        lines.extend(["- None captured.", ""])
        return lines
    lines.extend(f"- {item}" for item in items)
    lines.append("")
    return lines


def _requirement_summary_lines(requirements: list[RequirementRecord]) -> list[str]:
    lines: list[str] = []
    for requirement in requirements:
        details = [
            f"actor: {requirement.actor}" if requirement.actor else None,
            f"behavior: {requirement.behavior}" if requirement.behavior else None,
            f"goal: {requirement.goal}" if requirement.goal else None,
            f"priority: {requirement.priority}" if requirement.priority != "unknown" else None,
            f"owner: {requirement.owner}" if requirement.owner else None,
            f"status: {requirement.status}" if requirement.status != "proposed" else None,
        ]
        if requirement.constraints:
            details.append(f"constraints: {', '.join(requirement.constraints)}")
        if requirement.acceptance_criteria:
            details.append(f"acceptance: {', '.join(requirement.acceptance_criteria)}")
        detail_text = "; ".join(detail for detail in details if detail)
        if detail_text:
            lines.append(f"{requirement.text} ({detail_text})")
        else:
            lines.append(requirement.text)
    return lines


def _open_question_summary_lines(
    open_questions: list[OpenQuestionRecord],
    *,
    requirements: list[RequirementRecord],
) -> list[str]:
    requirement_labels = {
        requirement.requirement_id: requirement.behavior or requirement.text
        for requirement in requirements
    }
    lines: list[str] = []
    for question in open_questions:
        if question.answered:
            continue
        related = [
            _short_topic(requirement_labels[requirement_id])
            for requirement_id in question.related_requirement_ids
            if requirement_id in requirement_labels
        ]
        if related:
            lines.append(f"{question.text} (related: {', '.join(related)})")
        else:
            lines.append(question.text)
    return lines


def _decision_summary_lines(decisions: list[DecisionRecord]) -> list[str]:
    return [
        f"{decision.text} ({'confirmed' if decision.confirmed else 'unconfirmed'})"
        for decision in decisions
    ]


def _action_item_summary_lines(action_items: list[ActionItemRecord]) -> list[str]:
    lines: list[str] = []
    for action_item in action_items:
        details = ["completed" if action_item.completed else "open"]
        if action_item.owner:
            details.append(f"owner: {action_item.owner}")
        lines.append(f"{action_item.text} ({'; '.join(details)})")
    return lines


def _summary_file_stem(meeting_id: str | None, generated_at_ms: float) -> str:
    raw_id = meeting_id or "meeting"
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw_id).strip("-") or "meeting"
    return f"{safe_id}-{int(generated_at_ms)}"


def _context_summary_from_window(
    utterances: list[AgentUtterance],
    *,
    requirements: list[RequirementRecord],
    open_questions: list[OpenQuestionRecord],
    decisions: list[DecisionRecord],
    action_items: list[ActionItemRecord],
    risks: list[RiskRecord],
    parked_topics: list[ParkedTopicRecord],
) -> MeetingContextSummary:
    start = utterances[0]
    end = utterances[-1]
    topics = _context_topics(
        requirements=requirements,
        open_questions=open_questions,
        decisions=decisions,
        action_items=action_items,
        risks=risks,
        parked_topics=parked_topics,
    )
    speaker_count = len({item.speaker for item in utterances})
    text = (
        f"{len(utterances)} utterances from {speaker_count} speaker"
        f"{'' if speaker_count == 1 else 's'} covered "
        f"{', '.join(topics[:4]) if topics else 'general discussion'}."
    )
    return MeetingContextSummary(
        summary_id=uuid.uuid4().hex[:12],
        start_utterance_id=start.utterance_id,
        end_utterance_id=end.utterance_id,
        generated_at_ms=now_ms(),
        utterance_count=len(utterances),
        text=text,
        topics=topics,
    )


def _context_topics(
    *,
    requirements: list[RequirementRecord],
    open_questions: list[OpenQuestionRecord],
    decisions: list[DecisionRecord],
    action_items: list[ActionItemRecord],
    risks: list[RiskRecord],
    parked_topics: list[ParkedTopicRecord],
) -> list[str]:
    topics: list[str] = []
    for values in [
        [item.behavior or item.text for item in requirements[-3:]],
        [item.text for item in decisions[-2:]],
        [item.text for item in open_questions[-2:] if not item.answered],
        [item.text for item in action_items[-2:]],
        [item.text for item in risks[-2:]],
        [item.text for item in parked_topics[-2:]],
    ]:
        for value in values:
            topic = _short_topic(value)
            if topic and topic not in topics:
                topics.append(topic)
    return topics


def _short_topic(text: str) -> str:
    topic = _normalize_record_text(text).rstrip(".?")
    if len(topic) > 80:
        topic = f"{topic[:77].rstrip()}..."
    return topic


def _truncate_summary_text(text: str) -> str:
    summary = _normalize_record_text(text).rstrip()
    if len(summary) > 320:
        summary = f"{summary[:317].rstrip()}..."
    return summary


def _preview_text(text: str | None) -> str | None:
    if text is None:
        return None
    preview = _normalize_record_text(text)
    if len(preview) > 160:
        preview = f"{preview[:157].rstrip()}..."
    return preview or None


def _provider_name(llm_client: object | None) -> str:
    if llm_client is None:
        return "none"
    return type(llm_client).__name__


def _find_by_record_key[RecordT: TextRecord](
    records: deque[RecordT],
    text: str,
) -> RecordT | None:
    keys = _record_keys(text)
    return next((record for record in records if _record_keys(record.text) & keys), None)


def _record_key(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]+", " ", text.lower())
    return " ".join(normalized.split())


def _record_keys(text: str) -> set[str]:
    keys = {_record_key(text)}
    semantic_key = _semantic_record_key(text)
    if semantic_key:
        keys.add(semantic_key)
    return {key for key in keys if key}


def _semantic_record_key(text: str) -> str | None:
    normalized = _normalize_record_text(text).rstrip(".")
    if _looks_like_requirement(normalized):
        fields = _requirement_fields(normalized)
        parts = [fields.actor, fields.behavior]
        if any(parts):
            return _record_key(" ".join(part for part in parts if part))
    lowered = normalized.lower()
    prefix_patterns = [
        r"^(?:what|when|where|why|how|who)\s+(?:is|are|do|does|can|could|should)\s+(.+)$",
        r"^(?:we\s+)?decided\s+(?:that\s+)?(?:to\s+)?(.+)$",
        r"^(?:the\s+)?decision\s+is\s+(?:to\s+)?(.+)$",
        r"^(?:action item|todo|to do)[:\s-]+(.+)$",
        r"^(?:risk|concern|blocker)[:\s-]+(.+)$",
        r"^(?:parking lot|parked topic|follow[-\s]?up)[:\s-]+(.+)$",
    ]
    for pattern in prefix_patterns:
        match = re.match(pattern, lowered)
        if match is not None:
            value = _topic_key(match.group(1))
            if value:
                return value
    if _looks_like_question(normalized):
        return _topic_key(lowered)
    return None


def _topic_key(text: str) -> str:
    key = _record_key(text)
    key = re.sub(r"^(?:the|a|an)\s+", "", key)
    return key


def _merge_sources(record: TextRecord, source_utterance_id: str) -> None:
    if not record.source_utterance_ids:
        record.source_utterance_ids.append(source_utterance_id)
        return
    if source_utterance_id not in record.source_utterance_ids:
        record.source_utterance_ids.append(source_utterance_id)


def _merge_related_requirement_ids(
    record: OpenQuestionRecord,
    related_requirement_ids: list[str],
) -> None:
    for requirement_id in related_requirement_ids:
        if requirement_id not in record.related_requirement_ids:
            record.related_requirement_ids.append(requirement_id)


def _question_links_to_requirement(
    question_terms: set[str],
    requirement: RequirementRecord,
) -> bool:
    if not question_terms:
        return False
    requirement_terms = _link_terms(
        " ".join(
            value
            for value in [
                requirement.text,
                requirement.actor or "",
                requirement.goal or "",
                requirement.behavior or "",
                " ".join(requirement.constraints),
            ]
            if value
        )
    )
    if not requirement_terms:
        return False
    shared = question_terms & requirement_terms
    if len(shared) >= 2:
        return True
    specific_question_terms = question_terms - _GENERIC_QUESTION_TERMS
    return bool(shared and len(specific_question_terms) <= 2)


def _answer_links_to_question(
    answer_text: str,
    answer_terms: set[str],
    question: OpenQuestionRecord,
) -> bool:
    if _explicit_answer_reference(answer_text):
        return True
    question_terms = _link_terms(question.text) - _GENERIC_QUESTION_TERMS
    if not question_terms:
        return False
    shared = question_terms & answer_terms
    if len(shared) >= 2:
        return True
    return bool(shared and len(question_terms) <= 2)


def _explicit_answer_reference(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.match(
            r"^(?:answer|answered|to answer|the answer is|that answers|this answers)\b",
            normalized,
        )
    )


_GENERIC_QUESTION_TERMS = {
    "acceptance",
    "criteria",
    "definition",
    "done",
    "scope",
    "requirement",
    "requirements",
    "use",
    "what",
    "when",
    "where",
    "why",
    "how",
    "who",
    "which",
    "should",
    "could",
    "would",
    "need",
    "needs",
}


_LINK_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "before",
    "by",
    "can",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "we",
    "with",
}


def _link_terms(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\s]+", " ", text.lower())
    terms = {
        term
        for term in normalized.split()
        if len(term) >= 3 and term not in _LINK_STOP_WORDS
    }
    if "users" in terms:
        terms.add("user")
    if "invoices" in terms:
        terms.add("invoice")
    if "admins" in terms:
        terms.add("admin")
    return terms


def _merge_optional_requirement_fields(
    existing: RequirementRecord,
    incoming: RequirementRecord,
) -> None:
    if existing.actor is None and incoming.actor is not None:
        existing.actor = incoming.actor
    if existing.goal is None and incoming.goal is not None:
        existing.goal = incoming.goal
    if existing.behavior is None and incoming.behavior is not None:
        existing.behavior = incoming.behavior
    if existing.owner is None and incoming.owner is not None:
        existing.owner = incoming.owner
    if existing.priority == "unknown" and incoming.priority != "unknown":
        existing.priority = incoming.priority
    if existing.status == "proposed" and incoming.status != "proposed":
        existing.status = incoming.status
    for constraint in incoming.constraints:
        if constraint not in existing.constraints:
            existing.constraints.append(constraint)
    for criterion in incoming.acceptance_criteria:
        if criterion not in existing.acceptance_criteria:
            existing.acceptance_criteria.append(criterion)


def _max_risk_severity(left: str, right: str) -> str:
    order = {"unknown": 0, "medium": 1, "high": 2}
    return left if order.get(left, 0) >= order.get(right, 0) else right
