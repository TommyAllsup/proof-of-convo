from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from typing import Protocol
from urllib import request

from backend.models.agent import (
    ActionItemRecord,
    AgentParticipationMode,
    AgentReasoningDecision,
    AgentRuntimeState,
    DecisionRecord,
    MeetingContextSummary,
    OpenQuestionRecord,
    ParkedTopicRecord,
    RequirementRecord,
    RiskRecord,
)


@dataclass(frozen=True)
class DirectAnswerContext:
    question: str
    current_topic: str | None
    recent_utterances: list[str]
    requirements: list[RequirementRecord]
    open_questions: list[OpenQuestionRecord]
    decisions: list[DecisionRecord]


@dataclass(frozen=True)
class ReasoningContext:
    mode: AgentParticipationMode
    runtime_state: AgentRuntimeState
    utterance: str
    context_summaries: list[MeetingContextSummary]
    current_topic: str | None
    recent_utterances: list[str]
    requirements: list[RequirementRecord]
    open_questions: list[OpenQuestionRecord]
    decisions: list[DecisionRecord]
    cooldown_allows_speech: bool
    can_auto_speak: bool


@dataclass(frozen=True)
class ContextSummaryRequest:
    utterances: list[str]
    requirements: list[RequirementRecord]
    open_questions: list[OpenQuestionRecord]
    decisions: list[DecisionRecord]
    action_items: list[ActionItemRecord]
    risks: list[RiskRecord]
    parked_topics: list[ParkedTopicRecord]


class MeetingReasoner(Protocol):
    def answer_direct_question(self, context: DirectAnswerContext) -> str: ...


class LLMClient(Protocol):
    def decide(self, context: ReasoningContext) -> AgentReasoningDecision: ...

    def answer_direct_question(self, context: DirectAnswerContext) -> str: ...

    def summarize_context(self, context: ContextSummaryRequest) -> str: ...


class DeterministicMeetingReasoner:
    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        question = _clean_direct_question(context.question)
        if not context.requirements and not context.decisions and not context.open_questions:
            if question:
                return (
                    "I do not have enough meeting context to answer that yet. "
                    "I can help track the requirement, decision, and open question "
                    "as we clarify it."
                )
            return "I am here and tracking the requirements discussion."

        parts = ["Based on what I have captured so far:"]
        latest_decision = context.decisions[-1] if context.decisions else None
        latest_requirement = context.requirements[-1] if context.requirements else None
        latest_question = _latest_unanswered_question(context.open_questions)

        if latest_decision is not None:
            parts.append(f"the latest decision is {latest_decision.text}.")
        if latest_requirement is not None:
            parts.append(f"the latest requirement is: {latest_requirement.text}")
        if latest_question is not None:
            parts.append(f"one open question is: {latest_question.text}")

        if question:
            parts.append("If you want a firmer answer, I need the owner and acceptance criteria.")
        return " ".join(parts)


class FakeLLMClient:
    def __init__(
        self,
        decisions: list[AgentReasoningDecision] | None = None,
        direct_answers: list[str] | None = None,
        context_summaries: list[str] | None = None,
    ) -> None:
        self._decisions = list(decisions or [])
        self._direct_answers = list(direct_answers or [])
        self._context_summaries = list(context_summaries or [])

    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        if self._direct_answers:
            return self._direct_answers.pop(0)
        topic = context.current_topic or "the current requirements discussion"
        return f"I can help with {topic}, but I need the owner and acceptance criteria to be firm."

    def summarize_context(self, context: ContextSummaryRequest) -> str:
        if self._context_summaries:
            return self._context_summaries.pop(0)
        return (
            f"{len(context.utterances)} recent utterances covered "
            f"{context.requirements[-1].behavior or context.requirements[-1].text}"
            if context.requirements
            else f"{len(context.utterances)} recent utterances covered general discussion"
        )

    def decide(self, context: ReasoningContext) -> AgentReasoningDecision:
        if self._decisions:
            return self._decisions.pop(0)
        if context.requirements and _looks_requirement_like(context.utterance):
            requirement = context.requirements[-1]
            topic = requirement.behavior or requirement.text
            return AgentReasoningDecision(
                action="ask_clarifying_question",
                candidate_type="clarifying_question",
                text=f"What acceptance criteria would make '{topic}' done?",
                score=0.74,
                reason="fake llm identified a requirement that needs acceptance criteria",
            )
        return AgentReasoningDecision(
            action="listen",
            score=0.0,
            reason="fake llm found no useful contribution",
        )


class OpenAIResponsesLLMClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 2.0,
        max_output_tokens: int = 220,
        reasoning_prompt_suffix: str | None = None,
        direct_answer_prompt_suffix: str | None = None,
        context_summary_prompt_suffix: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._max_output_tokens = max_output_tokens
        self._reasoning_prompt_suffix = reasoning_prompt_suffix
        self._direct_answer_prompt_suffix = direct_answer_prompt_suffix
        self._context_summary_prompt_suffix = context_summary_prompt_suffix

    def decide(self, context: ReasoningContext) -> AgentReasoningDecision:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is required for PROOF_AGENT_LLM_PROVIDER=openai")
        body = {
            "model": self._model,
            "input": [
                {
                    "role": "system",
                    "content": _with_prompt_suffix(
                        _reasoning_system_prompt(),
                        self._reasoning_prompt_suffix,
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(_reasoning_context_payload(context), ensure_ascii=False),
                },
            ],
            "max_output_tokens": self._max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "agent_reasoning_decision",
                    "strict": True,
                    "schema": _agent_reasoning_json_schema(),
                }
            },
        }
        api_request = request.Request(
            f"{self._base_url}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(api_request, timeout=self._timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return AgentReasoningDecision.model_validate_json(_response_text(payload))

    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is required for PROOF_AGENT_LLM_PROVIDER=openai")
        body = {
            "model": self._model,
            "input": [
                {
                    "role": "system",
                    "content": _with_prompt_suffix(
                        _direct_answer_system_prompt(),
                        self._direct_answer_prompt_suffix,
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        _direct_answer_context_payload(context),
                        ensure_ascii=False,
                    ),
                },
            ],
            "max_output_tokens": self._max_output_tokens,
        }
        api_request = request.Request(
            f"{self._base_url}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(api_request, timeout=self._timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return _response_text(payload).strip()

    def summarize_context(self, context: ContextSummaryRequest) -> str:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is required for PROOF_AGENT_LLM_PROVIDER=openai")
        body = {
            "model": self._model,
            "input": [
                {
                    "role": "system",
                    "content": _with_prompt_suffix(
                        _context_summary_system_prompt(),
                        self._context_summary_prompt_suffix,
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        _context_summary_payload(context),
                        ensure_ascii=False,
                    ),
                },
            ],
            "max_output_tokens": self._max_output_tokens,
        }
        api_request = request.Request(
            f"{self._base_url}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(api_request, timeout=self._timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return _response_text(payload).strip()


class MlxLmLLMClient:
    def __init__(
        self,
        *,
        model: str,
        max_output_tokens: int = 220,
        reasoning_prompt_suffix: str | None = None,
        direct_answer_prompt_suffix: str | None = None,
        context_summary_prompt_suffix: str | None = None,
    ) -> None:
        self._model_id = model
        self._max_output_tokens = max_output_tokens
        self._reasoning_prompt_suffix = reasoning_prompt_suffix
        self._direct_answer_prompt_suffix = direct_answer_prompt_suffix
        self._context_summary_prompt_suffix = context_summary_prompt_suffix
        self._model: object | None = None
        self._tokenizer: object | None = None
        self._generate: Callable[..., str] | None = None

    def decide(self, context: ReasoningContext) -> AgentReasoningDecision:
        response = self._generate_text(
            system_prompt=_with_prompt_suffix(
                _reasoning_system_prompt()
                + " Return only one compact JSON object matching the requested schema.",
                self._reasoning_prompt_suffix,
            ),
            payload={
                "schema_name": "agent_reasoning_decision",
                "schema": _agent_reasoning_json_schema(),
                "context": _reasoning_context_payload(context),
            },
        )
        return AgentReasoningDecision.model_validate_json(_extract_json_object(response))

    def answer_direct_question(self, context: DirectAnswerContext) -> str:
        return self._generate_text(
            system_prompt=_with_prompt_suffix(
                _direct_answer_system_prompt(),
                self._direct_answer_prompt_suffix,
            ),
            payload=_direct_answer_context_payload(context),
        ).strip()

    def summarize_context(self, context: ContextSummaryRequest) -> str:
        return self._generate_text(
            system_prompt=_with_prompt_suffix(
                _context_summary_system_prompt(),
                self._context_summary_prompt_suffix,
            ),
            payload=_context_summary_payload(context),
        ).strip()

    def _generate_text(self, *, system_prompt: str, payload: dict[str, object]) -> str:
        model, tokenizer, generate = self._load()
        prompt = _chat_prompt(tokenizer, system_prompt=system_prompt, payload=payload)
        return generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=self._max_output_tokens,
            verbose=False,
        )

    def _load(self) -> tuple[object, object, Callable[..., str]]:
        if self._model is not None and self._tokenizer is not None and self._generate is not None:
            return self._model, self._tokenizer, self._generate
        try:
            import mlx_lm
        except Exception as exc:  # noqa: BLE001 - optional local provider.
            raise RuntimeError(
                "mlx_lm is required for PROOF_AGENT_LLM_PROVIDER=mlx_lm. "
                "Install the mlx-lm extra/package on Apple Silicon."
            ) from exc
        module = mlx_lm if isinstance(mlx_lm, ModuleType) else mlx_lm
        load = getattr(module, "load", None)
        generate = getattr(module, "generate", None)
        if not callable(load) or not callable(generate):
            raise RuntimeError("mlx_lm must expose callable load and generate functions")
        self._model, self._tokenizer = load(self._model_id)
        self._generate = generate
        return self._model, self._tokenizer, self._generate


def create_llm_client(
    provider: str,
    *,
    api_key: str | None = None,
    model: str = "gpt-5.5",
    base_url: str = "https://api.openai.com/v1",
    timeout_s: float = 2.0,
    max_output_tokens: int = 220,
    reasoning_prompt_suffix: str | None = None,
    direct_answer_prompt_suffix: str | None = None,
    context_summary_prompt_suffix: str | None = None,
) -> LLMClient | None:
    normalized = provider.strip().lower()
    if normalized in {"", "none", "off", "disabled"}:
        return None
    if normalized == "fake":
        return FakeLLMClient()
    if normalized == "openai":
        return OpenAIResponsesLLMClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_s=timeout_s,
            max_output_tokens=max_output_tokens,
            reasoning_prompt_suffix=reasoning_prompt_suffix,
            direct_answer_prompt_suffix=direct_answer_prompt_suffix,
            context_summary_prompt_suffix=context_summary_prompt_suffix,
        )
    if normalized in {"mlx_lm", "mlx-lm", "mlx"}:
        model_id = (
            "mlx-community/Qwen2.5-7B-Instruct-4bit"
            if model == "gpt-5.5"
            else model
        )
        return MlxLmLLMClient(
            model=model_id,
            max_output_tokens=max_output_tokens,
            reasoning_prompt_suffix=reasoning_prompt_suffix,
            direct_answer_prompt_suffix=direct_answer_prompt_suffix,
            context_summary_prompt_suffix=context_summary_prompt_suffix,
        )
    raise ValueError(f"Unsupported PROOF_AGENT_LLM_PROVIDER={provider!r}")


def _clean_direct_question(text: str) -> str:
    return text.strip()


def _looks_requirement_like(text: str) -> bool:
    normalized = text.strip().lower()
    return any(
        phrase in normalized
        for phrase in [
            "we need",
            "we should",
            "we must",
            "users must",
            "users should",
            "users need",
            "the system should",
            "the system must",
            "requirement",
        ]
    )


def _latest_unanswered_question(
    questions: list[OpenQuestionRecord],
) -> OpenQuestionRecord | None:
    for question in reversed(questions):
        if not question.answered:
            return question
    return None


def _reasoning_system_prompt() -> str:
    return (
        "You are Erica, a concise meeting participant and requirements facilitator. "
        "Decide whether one useful intervention is warranted. Prefer listen unless a clear "
        "clarifying question would improve requirements quality. Never draft more than one "
        "question. If the meeting needs a different participation stance, suggest a mode change "
        "for operator approval instead of changing modes yourself. When the latest utterance "
        "clarifies an existing requirement, include a requirement_refinement patch targeted to an "
        "existing requirement_id. Do not invent unmentioned facts."
    )


def _direct_answer_system_prompt() -> str:
    return (
        "You are Erica, a concise meeting participant and requirements facilitator. "
        "Answer the direct question using only the provided meeting context. Keep the answer "
        "spoken, specific, and under 45 words. If context is insufficient, say what is missing."
    )


def _context_summary_system_prompt() -> str:
    return (
        "You are Erica, a concise meeting requirements scribe. Summarize the recent transcript "
        "window in one factual sentence under 45 words. Include concrete requirements, decisions, "
        "open questions, risks, or actions when present. Use only provided context."
    )


def _with_prompt_suffix(prompt: str, suffix: str | None) -> str:
    if suffix is None or not suffix.strip():
        return prompt
    return f"{prompt}\n\nLive tuning instructions:\n{suffix.strip()}"


def _chat_prompt(tokenizer: object, *, system_prompt: str, payload: dict[str, object]) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
    if callable(apply_chat_template):
        prompt = apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        if isinstance(prompt, str):
            return prompt
    return "\n\n".join(
        [
            f"System: {system_prompt}",
            f"User: {json.dumps(payload, ensure_ascii=False)}",
            "Assistant:",
        ]
    )


def _direct_answer_context_payload(context: DirectAnswerContext) -> dict[str, object]:
    return {
        "question": context.question,
        "current_topic": context.current_topic,
        "recent_utterances": context.recent_utterances[-8:],
        "requirements": [item.model_dump(mode="json") for item in context.requirements[-8:]],
        "open_questions": [item.model_dump(mode="json") for item in context.open_questions[-8:]],
        "decisions": [item.model_dump(mode="json") for item in context.decisions[-8:]],
    }


def _context_summary_payload(context: ContextSummaryRequest) -> dict[str, object]:
    return {
        "utterances": context.utterances[-10:],
        "requirements": [item.model_dump(mode="json") for item in context.requirements[-8:]],
        "open_questions": [item.model_dump(mode="json") for item in context.open_questions[-8:]],
        "decisions": [item.model_dump(mode="json") for item in context.decisions[-8:]],
        "action_items": [item.model_dump(mode="json") for item in context.action_items[-8:]],
        "risks": [item.model_dump(mode="json") for item in context.risks[-8:]],
        "parked_topics": [item.model_dump(mode="json") for item in context.parked_topics[-8:]],
    }


def _reasoning_context_payload(context: ReasoningContext) -> dict[str, object]:
    return {
        "mode": context.mode,
        "runtime_state": context.runtime_state,
        "utterance": context.utterance,
        "current_topic": context.current_topic,
        "context_summaries": [
            item.model_dump(mode="json") for item in context.context_summaries[-6:]
        ],
        "recent_utterances": context.recent_utterances[-8:],
        "requirements": [item.model_dump(mode="json") for item in context.requirements[-8:]],
        "open_questions": [item.model_dump(mode="json") for item in context.open_questions[-8:]],
        "decisions": [item.model_dump(mode="json") for item in context.decisions[-8:]],
        "cooldown_allows_speech": context.cooldown_allows_speech,
        "can_auto_speak": context.can_auto_speak,
    }


def _agent_reasoning_json_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "listen",
                    "draft_candidate",
                    "speak_now",
                    "summarize",
                    "capture_decision",
                    "ask_clarifying_question",
                    "suggest_mode_change",
                ],
            },
            "candidate_type": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": [
                            "direct_answer",
                            "clarifying_question",
                            "gap_detection",
                            "conflict_detection",
                            "decision_capture",
                            "scope_control",
                            "summary_checkpoint",
                            "mode_change",
                        ],
                    },
                    {"type": "null"},
                ]
            },
            "text": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reason": {"type": "string"},
            "suggested_mode": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": ["off", "passive", "assistant", "facilitator", "qa", "scribe"],
                    },
                    {"type": "null"},
                ]
            },
            "requirement_refinement": {
                "anyOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "target_requirement_id": {
                                "anyOf": [{"type": "string"}, {"type": "null"}]
                            },
                            "text": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "actor": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "goal": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "behavior": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "constraints": {"type": "array", "items": {"type": "string"}},
                            "priority": {
                                "type": "string",
                                "enum": ["unknown", "low", "medium", "high"],
                            },
                            "owner": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "status": {
                                "anyOf": [
                                    {
                                        "type": "string",
                                        "enum": ["proposed", "clarifying", "accepted", "deferred"],
                                    },
                                    {"type": "null"},
                                ]
                            },
                            "acceptance_criteria": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "open_questions": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "target_requirement_id",
                            "text",
                            "actor",
                            "goal",
                            "behavior",
                            "constraints",
                            "priority",
                            "owner",
                            "status",
                            "acceptance_criteria",
                            "open_questions",
                        ],
                    },
                    {"type": "null"},
                ]
            },
        },
        "required": [
            "action",
            "candidate_type",
            "text",
            "score",
            "reason",
            "suggested_mode",
            "requirement_refinement",
        ],
    }


def _response_text(payload: dict[str, object]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = payload.get("output")
    if not isinstance(output, list):
        raise RuntimeError("OpenAI response missing output text")
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                return text
    raise RuntimeError("OpenAI response missing output text")


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    raise RuntimeError("MLX-LM response missing JSON object")
