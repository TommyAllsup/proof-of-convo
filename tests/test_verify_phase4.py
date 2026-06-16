from pathlib import Path

from scripts.verify_phase4 import run_verification


def test_phase4_preflight_passes_and_writes_artifact(tmp_path: Path) -> None:
    report = run_verification(artifact_dir=tmp_path)

    assert report.passed is True
    assert {check.name for check in report.checks} == {
        "direct_address_speech",
        "mode_voice_command",
        "facilitator_waits_for_turn",
        "facilitator_auto_speech",
        "structured_memory",
        "context_summary",
        "provider_telemetry",
        "meeting_summary",
    }
    assert all(check.ok for check in report.checks)
    assert report.artifact_path is not None
    assert Path(report.artifact_path).exists()
    assert '"passed": true' in Path(report.artifact_path).read_text(encoding="utf-8")
