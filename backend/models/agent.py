from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentParticipationMode = Literal["off", "passive", "assistant", "facilitator", "qa", "scribe"]
MeetingLifecycleState = Literal[
    "not_in_meeting",
    "joining_meeting",
    "meeting_started",
    "in_meeting",
    "ending_meeting",
    "meeting_ended",
]
AgentRuntimeState = Literal[
    "idle_listening",
    "candidate_intervention",
    "waiting_for_turn",
    "thinking",
    "speaking",
    "interrupted",
    "cooldown",
    "manual_override",
]
RequirementPriority = Literal["unknown", "low", "medium", "high"]
RequirementStatus = Literal["proposed", "clarifying", "accepted", "deferred"]
AgentReasoningAction = Literal[
    "listen",
    "draft_candidate",
    "speak_now",
    "summarize",
    "capture_decision",
    "ask_clarifying_question",
    "suggest_mode_change",
]
InterventionType = Literal[
    "direct_answer",
    "clarifying_question",
    "gap_detection",
    "conflict_detection",
    "decision_capture",
    "scope_control",
    "summary_checkpoint",
    "mode_change",
]


class AgentUtterance(BaseModel):
    utterance_id: str
    session_id: str
    speaker: str
    text: str
    start_ms: float
    end_ms: float
    received_at_ms: float


class ParticipantState(BaseModel):
    speaker: str
    utterance_count: int = 0
    last_heard_at_ms: float | None = None


class AgentCandidateIntervention(BaseModel):
    candidate_id: str
    type: InterventionType
    text: str
    score: float = Field(ge=0.0, le=1.0)
    speak_allowed: bool
    reason: str
    source_utterance_id: str | None = None
    suggested_mode: AgentParticipationMode | None = None
    created_at_ms: float


class RequirementRefinement(BaseModel):
    target_requirement_id: str | None = None
    text: str | None = None
    actor: str | None = None
    goal: str | None = None
    behavior: str | None = None
    constraints: list[str] = Field(default_factory=list)
    priority: RequirementPriority = "unknown"
    owner: str | None = None
    status: RequirementStatus | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class AgentReasoningDecision(BaseModel):
    action: AgentReasoningAction
    candidate_type: InterventionType | None = None
    text: str | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str
    suggested_mode: AgentParticipationMode | None = None
    requirement_refinement: RequirementRefinement | None = None


class AgentReasoningTrace(BaseModel):
    trace_id: str
    utterance_id: str
    action: AgentReasoningAction | None = None
    candidate_type: InterventionType | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = None
    suggested_mode: AgentParticipationMode | None = None
    error: str | None = None
    created_at_ms: float
    mode: AgentParticipationMode
    runtime_state: AgentRuntimeState
    can_auto_speak: bool
    cooldown_allows_speech: bool
    context_summary_count: int
    recent_utterance_count: int


class AgentLLMCallTrace(BaseModel):
    trace_id: str
    operation: Literal["reasoning", "direct_answer", "context_summary"]
    provider: str
    success: bool
    latency_ms: float = Field(ge=0.0)
    error: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    created_at_ms: float


class AgentSettings(BaseModel):
    aggressiveness: int = Field(default=25, ge=0, le=100)
    direct_answer_cooldown_ms: float = Field(default=8_000.0, ge=0.0, le=120_000.0)
    proactive_min_silence_ms: float = Field(default=1_200.0, ge=0.0, le=30_000.0)


class AgentReadiness(BaseModel):
    can_auto_speak: bool = True
    blockers: list[str] = Field(default_factory=list)


class RequirementRecord(BaseModel):
    requirement_id: str
    text: str
    source_utterance_id: str
    source_utterance_ids: list[str] = Field(default_factory=list)
    speaker: str
    created_at_ms: float
    actor: str | None = None
    goal: str | None = None
    behavior: str | None = None
    constraints: list[str] = Field(default_factory=list)
    priority: RequirementPriority = "unknown"
    owner: str | None = None
    status: RequirementStatus = "proposed"
    acceptance_criteria: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class OpenQuestionRecord(BaseModel):
    question_id: str
    text: str
    source_utterance_id: str
    source_utterance_ids: list[str] = Field(default_factory=list)
    speaker: str
    created_at_ms: float
    answered: bool = False
    related_requirement_ids: list[str] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    decision_id: str
    text: str
    source_utterance_id: str
    source_utterance_ids: list[str] = Field(default_factory=list)
    speaker: str
    created_at_ms: float
    confirmed: bool = False


class ActionItemRecord(BaseModel):
    action_item_id: str
    text: str
    source_utterance_id: str
    source_utterance_ids: list[str] = Field(default_factory=list)
    speaker: str
    created_at_ms: float
    owner: str | None = None
    completed: bool = False


class RiskRecord(BaseModel):
    risk_id: str
    text: str
    source_utterance_id: str
    source_utterance_ids: list[str] = Field(default_factory=list)
    speaker: str
    created_at_ms: float
    severity: str = "unknown"
    mitigated: bool = False


class ParkedTopicRecord(BaseModel):
    parked_topic_id: str
    text: str
    source_utterance_id: str
    source_utterance_ids: list[str] = Field(default_factory=list)
    speaker: str
    created_at_ms: float
    revisited: bool = False


class MeetingContextSummary(BaseModel):
    summary_id: str
    start_utterance_id: str
    end_utterance_id: str
    generated_at_ms: float
    utterance_count: int
    text: str
    topics: list[str] = Field(default_factory=list)


class CurrentTopicState(BaseModel):
    topic: str
    source_utterance_id: str
    updated_at_ms: float


class MeetingSummaryArtifact(BaseModel):
    meeting_id: str | None = None
    meeting_url: str | None = None
    generated_at_ms: float
    utterance_count: int
    participant_count: int
    requirements: list[RequirementRecord]
    open_questions: list[OpenQuestionRecord]
    decisions: list[DecisionRecord]
    action_items: list[ActionItemRecord]
    risks: list[RiskRecord]
    parked_topics: list[ParkedTopicRecord]
    context_summaries: list[MeetingContextSummary]
    current_topic: CurrentTopicState | None = None
    candidate_interventions: list[AgentCandidateIntervention]
    markdown: str
    json_path: str | None = None
    markdown_path: str | None = None


class AgentStatus(BaseModel):
    name: str = "Erica"
    mode: AgentParticipationMode
    lifecycle_state: MeetingLifecycleState
    runtime_state: AgentRuntimeState
    meeting_id: str | None = None
    meeting_url: str | None = None
    recent_utterances: list[AgentUtterance]
    participants: list[ParticipantState]
    requirements: list[RequirementRecord]
    open_questions: list[OpenQuestionRecord]
    decisions: list[DecisionRecord]
    action_items: list[ActionItemRecord]
    risks: list[RiskRecord]
    parked_topics: list[ParkedTopicRecord]
    context_summaries: list[MeetingContextSummary]
    current_topic: CurrentTopicState | None = None
    candidate_interventions: list[AgentCandidateIntervention]
    reasoning_traces: list[AgentReasoningTrace]
    llm_call_traces: list[AgentLLMCallTrace]
    latest_summary: MeetingSummaryArtifact | None = None
    settings: AgentSettings = Field(default_factory=AgentSettings)
    readiness: AgentReadiness = Field(default_factory=AgentReadiness)
    active_speech_job_id: str | None = None
    last_speech_job_id: str | None = None
    last_agent_speech_at_ms: float | None = None
    last_human_speech_at_ms: float | None = None
    last_state_change_at_ms: float
    last_error: str | None = None


class AgentModeRequest(BaseModel):
    mode: AgentParticipationMode


class AgentSettingsRequest(BaseModel):
    aggressiveness: int = Field(ge=0, le=100)
    direct_answer_cooldown_ms: float | None = Field(default=None, ge=0.0, le=120_000.0)
    proactive_min_silence_ms: float | None = Field(default=None, ge=0.0, le=30_000.0)


class AgentLifecycleResponse(BaseModel):
    status: AgentStatus


class AgentBeginMeetingRequest(BaseModel):
    meeting_id: str | None = None
    meeting_url: str | None = None


class AgentEndMeetingRequest(BaseModel):
    reason: str = "manual"


class AgentSpeakCandidateRequest(BaseModel):
    candidate_id: str
    interrupt: bool = True


class AgentDismissCandidateRequest(BaseModel):
    candidate_id: str


class AgentApplyCandidateRequest(BaseModel):
    candidate_id: str


class AgentInjectTranscriptRequest(BaseModel):
    text: str = Field(min_length=1)
    speaker: str = "Manual"
    session_id: str | None = None
    utterance_id: str | None = None
    start_ms: float | None = Field(default=None, ge=0.0)
    end_ms: float | None = Field(default=None, ge=0.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
