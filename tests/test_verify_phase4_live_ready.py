from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts import verify_phase4_live_ready
from scripts.verify_phase3 import CheckResult as Phase3CheckResult


@dataclass(frozen=True)
class _TestSettings:
    stt_enabled: bool
    stt_provider: str
    tts_enabled: bool
    tts_playback_enabled: bool
    tts_output_device: str | None


def test_extension_checks_pass_when_dist_contains_required_files(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    for path in [
        dist / "manifest.json",
        dist / "popup.html",
        dist / "sidepanel.html",
        dist / "offscreen.html",
        dist / "assets" / "background.js",
        dist / "assets" / "offscreen.js",
        dist / "assets" / "content.js",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")

    checks = verify_phase4_live_ready._extension_checks(dist)

    assert checks == [
        verify_phase4_live_ready.LiveReadyCheck(
            name="Chrome extension build",
            ok=True,
            detail="ready",
        )
    ]


def test_extension_checks_fail_when_dist_is_missing(tmp_path: Path) -> None:
    checks = verify_phase4_live_ready._extension_checks(tmp_path / "missing")

    assert checks[0].ok is False
    assert "manifest.json" in checks[0].detail


def test_phase3_results_are_preserved_as_readiness_checks() -> None:
    checks = verify_phase4_live_ready._phase3_readiness_checks(
        [
            Phase3CheckResult(name="virtual mic output device", ok=False, detail="missing"),
            Phase3CheckResult(
                name="BlackHole Homebrew cask",
                ok=False,
                detail="not installed",
                required=False,
            ),
        ]
    )

    assert checks == [
        verify_phase4_live_ready.LiveReadyCheck(
            name="phase3: virtual mic output device",
            ok=False,
            detail="missing",
        ),
        verify_phase4_live_ready.LiveReadyCheck(
            name="phase3: BlackHole Homebrew cask",
            ok=False,
            detail="not installed",
            required=False,
        ),
    ]


def test_environment_checks_reflect_settings() -> None:
    checks = verify_phase4_live_ready._environment_checks(
        _TestSettings(
            stt_enabled=True,
            stt_provider="mlx_whisper",
            tts_enabled=True,
            tts_playback_enabled=True,
            tts_output_device="BlackHole 2ch",
        )
    )

    assert all(check.ok for check in checks)


def test_environment_checks_reject_fake_live_stt() -> None:
    checks = verify_phase4_live_ready._environment_checks(
        _TestSettings(
            stt_enabled=True,
            stt_provider="fake",
            tts_enabled=True,
            tts_playback_enabled=True,
            tts_output_device="BlackHole 2ch",
        )
    )

    assert checks[1].name == "live STT provider"
    assert checks[1].ok is False
