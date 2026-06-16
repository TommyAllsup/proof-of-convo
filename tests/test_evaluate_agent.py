from __future__ import annotations

from pathlib import Path

from scripts.evaluate_agent import (
    EvalScenario,
    EvalUtterance,
    default_scenarios,
    run_eval,
    run_scenario,
)


def test_default_phase4_agent_eval_passes(tmp_path: Path) -> None:
    report = run_eval(artifact_dir=tmp_path)

    assert report.passed is True
    assert report.score == 1.0
    assert len(report.scenarios) == len(default_scenarios())
    assert Path(report.artifacts["json"]).exists()
    markdown_path = Path(report.artifacts["markdown"])
    assert markdown_path.exists()
    assert "# Phase 4 Agent Behavior Eval" in markdown_path.read_text(encoding="utf-8")


def test_agent_eval_reports_failed_expectation() -> None:
    result = run_scenario(
        EvalScenario(
            scenario_id="bad-expectation",
            description="Intentional failure proves evaluator reports mismatch.",
            mode="passive",
            utterances=[EvalUtterance("Speaker_1", "We need an approval flow.")],
            expected_requirements=2,
            expected_candidate_types=["clarifying_question"],
        )
    )

    assert result.passed is False
    assert result.score < 1.0
    assert result.checks["requirements"] is False
    assert result.observed["requirements"] == 1
