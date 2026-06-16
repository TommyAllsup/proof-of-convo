from __future__ import annotations

import json
import sys
from collections.abc import Buffer
from types import ModuleType
from typing import Any
from urllib import request

import pytest

from backend.agent.reasoner import (
    ContextSummaryRequest,
    DirectAnswerContext,
    MlxLmLLMClient,
    OpenAIResponsesLLMClient,
    ReasoningContext,
    create_llm_client,
)


def test_openai_responses_client_sends_structured_output_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(api_request: request.Request, *, timeout: float) -> _FakeResponse:
        captured["url"] = api_request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(api_request.header_items())
        data = api_request.data
        assert isinstance(data, Buffer)
        captured["body"] = json.loads(bytes(data).decode("utf-8"))
        return _FakeResponse(
            {
                "output_text": json.dumps(
                    {
                        "action": "ask_clarifying_question",
                        "candidate_type": "clarifying_question",
                        "text": "Who owns invoice approvals?",
                        "score": 0.82,
                        "reason": "ownership is ambiguous",
                        "suggested_mode": None,
                        "requirement_refinement": None,
                    }
                )
            }
        )

    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    client = OpenAIResponsesLLMClient(
        api_key="test-key",
        model="gpt-test",
        base_url="https://api.example.test/v1/",
        timeout_s=1.5,
        max_output_tokens=123,
        reasoning_prompt_suffix="Prefer invoice owner questions in this test.",
    )

    decision = client.decide(_reasoning_context())

    assert decision.action == "ask_clarifying_question"
    assert decision.candidate_type == "clarifying_question"
    assert decision.text == "Who owns invoice approvals?"
    assert decision.score == 0.82
    assert captured["url"] == "https://api.example.test/v1/responses"
    assert captured["timeout"] == 1.5
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "gpt-test"
    assert captured["body"]["max_output_tokens"] == 123
    assert captured["body"]["text"]["format"]["type"] == "json_schema"
    assert captured["body"]["text"]["format"]["strict"] is True
    assert captured["body"]["text"]["format"]["schema"]["additionalProperties"] is False
    assert "requirement_refinement" in captured["body"]["text"]["format"]["schema"]["required"]
    assert "Prefer invoice owner questions" in captured["body"]["input"][0]["content"]
    assert "Prefer invoice owner questions" not in captured["body"]["input"][1]["content"]


def test_openai_responses_client_parses_nested_output_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(api_request: request.Request, *, timeout: float) -> _FakeResponse:
        _ = api_request, timeout
        return _FakeResponse(
            {
                "output": [
                    {
                        "content": [
                            {
                                "text": json.dumps(
                                    {
                                        "action": "listen",
                                        "candidate_type": None,
                                        "text": None,
                                        "score": 0.0,
                                        "reason": "no useful intervention",
                                        "suggested_mode": None,
                                        "requirement_refinement": None,
                                    }
                                )
                            }
                        ]
                    }
                ]
            }
        )

    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    client = OpenAIResponsesLLMClient(
        api_key="test-key",
        model="gpt-test",
        direct_answer_prompt_suffix="Answer as a concise product lead.",
    )

    decision = client.decide(_reasoning_context())

    assert decision.action == "listen"
    assert decision.reason == "no useful intervention"


def test_openai_responses_client_generates_direct_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(api_request: request.Request, *, timeout: float) -> _FakeResponse:
        _ = timeout
        data = api_request.data
        assert isinstance(data, Buffer)
        captured["body"] = json.loads(bytes(data).decode("utf-8"))
        return _FakeResponse({"output_text": "Use Google Meet first and defer Zoom."})

    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    client = OpenAIResponsesLLMClient(
        api_key="test-key",
        model="gpt-test",
        direct_answer_prompt_suffix="Answer as a concise product lead.",
    )

    answer = client.answer_direct_question(
        DirectAnswerContext(
            question="what should we use?",
            current_topic="platform choice",
            recent_utterances=["We decided to use Google Meet first."],
            requirements=[],
            open_questions=[],
            decisions=[],
        )
    )

    assert answer == "Use Google Meet first and defer Zoom."
    assert captured["body"]["model"] == "gpt-test"
    assert "text" not in captured["body"]
    assert "concise product lead" in captured["body"]["input"][0]["content"]
    assert captured["body"]["input"][1]["content"]


def test_openai_responses_client_generates_context_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(api_request: request.Request, *, timeout: float) -> _FakeResponse:
        _ = timeout
        data = api_request.data
        assert isinstance(data, Buffer)
        captured["body"] = json.loads(bytes(data).decode("utf-8"))
        return _FakeResponse({"output_text": "Invoices need approval and launch timing is open."})

    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    client = OpenAIResponsesLLMClient(
        api_key="test-key",
        model="gpt-test",
        context_summary_prompt_suffix="Mention unresolved launch risk when present.",
    )

    summary = client.summarize_context(
        ContextSummaryRequest(
            utterances=["Speaker_1: We need invoice approval.", "Speaker_2: What is launch?"],
            requirements=[],
            open_questions=[],
            decisions=[],
            action_items=[],
            risks=[],
            parked_topics=[],
        )
    )

    assert summary == "Invoices need approval and launch timing is open."
    assert captured["body"]["model"] == "gpt-test"
    assert "text" not in captured["body"]
    assert "unresolved launch risk" in captured["body"]["input"][0]["content"]
    assert "utterances" in captured["body"]["input"][1]["content"]


def test_openai_responses_client_requires_api_key() -> None:
    client = OpenAIResponsesLLMClient(api_key=None, model="gpt-test")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required"):
        client.decide(_reasoning_context())


def test_mlx_lm_client_generates_structured_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def load(model_id: str) -> tuple[object, object]:
        calls["model_id"] = model_id
        return object(), _FakeTokenizer()

    def generate(
        model: object,
        tokenizer: object,
        *,
        prompt: str,
        max_tokens: int,
        verbose: bool,
    ) -> str:
        _ = model, tokenizer, verbose
        calls["prompt"] = prompt
        calls["max_tokens"] = max_tokens
        return json.dumps(
            {
                "action": "ask_clarifying_question",
                "candidate_type": "clarifying_question",
                "text": "Who owns approvals?",
                "score": 0.81,
                "reason": "owner is missing",
                "suggested_mode": None,
                "requirement_refinement": None,
            }
        )

    monkeypatch.setitem(sys.modules, "mlx_lm", _fake_mlx_lm(load=load, generate=generate))

    client = MlxLmLLMClient(
        model="mlx-community/test-model",
        max_output_tokens=77,
        reasoning_prompt_suffix="Ask about owners first.",
    )
    decision = client.decide(_reasoning_context())

    assert decision.action == "ask_clarifying_question"
    assert decision.text == "Who owns approvals?"
    assert calls["model_id"] == "mlx-community/test-model"
    assert calls["max_tokens"] == 77
    assert "Ask about owners first" in calls["prompt"]
    assert "agent_reasoning_decision" in calls["prompt"]


def test_mlx_lm_client_generates_direct_answer_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = [
        "Use Google Meet first.",
        "The team chose Google Meet and still needs invoice criteria.",
    ]

    def generate(
        model: object,
        tokenizer: object,
        *,
        prompt: str,
        max_tokens: int,
        verbose: bool,
    ) -> str:
        _ = model, tokenizer, prompt, max_tokens, verbose
        return outputs.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "mlx_lm",
        _fake_mlx_lm(load=lambda model_id: (object(), _FakeTokenizer()), generate=generate),
    )
    client = MlxLmLLMClient(model="mlx-community/test-model")

    answer = client.answer_direct_question(
        DirectAnswerContext(
            question="what should we use?",
            current_topic="platform choice",
            recent_utterances=["We decided Google Meet first."],
            requirements=[],
            open_questions=[],
            decisions=[],
        )
    )
    summary = client.summarize_context(
        ContextSummaryRequest(
            utterances=["Speaker_1: We chose Google Meet."],
            requirements=[],
            open_questions=[],
            decisions=[],
            action_items=[],
            risks=[],
            parked_topics=[],
        )
    )

    assert answer == "Use Google Meet first."
    assert summary == "The team chose Google Meet and still needs invoice criteria."


def test_mlx_lm_client_requires_load_and_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mlx_lm", ModuleType("mlx_lm"))
    client = MlxLmLLMClient(model="mlx-community/test-model")

    with pytest.raises(RuntimeError, match="load and generate"):
        client.decide(_reasoning_context())


def test_create_llm_client_selects_mlx_lm_provider() -> None:
    client = create_llm_client("mlx_lm", model="mlx-community/test-model")

    assert isinstance(client, MlxLmLLMClient)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        _ = args

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _FakeTokenizer:
    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> str:
        _ = tokenize, add_generation_prompt
        return "\n".join(f"{item['role']}: {item['content']}" for item in messages)


def _fake_mlx_lm(
    *,
    load: object,
    generate: object,
) -> ModuleType:
    module = ModuleType("mlx_lm")
    module.load = load  # type: ignore[attr-defined]
    module.generate = generate  # type: ignore[attr-defined]
    return module


def _reasoning_context() -> ReasoningContext:
    return ReasoningContext(
        mode="facilitator",
        runtime_state="idle_listening",
        utterance="We need users to approve invoices before payment.",
        context_summaries=[],
        current_topic="approve invoices before payment",
        recent_utterances=["We need users to approve invoices before payment."],
        requirements=[],
        open_questions=[],
        decisions=[],
        cooldown_allows_speech=True,
        can_auto_speak=False,
    )
