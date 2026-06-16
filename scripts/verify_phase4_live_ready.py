from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.config import settings
from scripts.verify_phase3 import CheckResult as Phase3CheckResult
from scripts.verify_phase3 import run_checks as run_phase3_checks
from scripts.verify_phase4 import run_verification


@dataclass(frozen=True)
class LiveReadyCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


class LiveSettings(Protocol):
    @property
    def stt_enabled(self) -> bool: ...

    @property
    def stt_provider(self) -> str: ...

    @property
    def tts_enabled(self) -> bool: ...

    @property
    def tts_playback_enabled(self) -> bool: ...

    @property
    def tts_output_device(self) -> str | None: ...


@dataclass(frozen=True)
class _CurrentLiveSettings:
    stt_enabled: bool
    stt_provider: str
    tts_enabled: bool
    tts_playback_enabled: bool
    tts_output_device: str | None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check readiness for a real Phase 4 Google Meet validation run."
    )
    parser.add_argument("--device", default=settings.tts_output_device or "BlackHole")
    parser.add_argument("--tts-provider", default=settings.tts_provider)
    parser.add_argument("--extension-dist", type=Path, default=Path("extension/dist"))
    parser.add_argument("--artifact-dir", type=Path, default=Path(".data/phase4-live-ready"))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    checks = run_live_readiness(
        device=args.device,
        tts_provider=args.tts_provider,
        extension_dist=args.extension_dist,
        artifact_dir=args.artifact_dir,
    )
    for check in checks:
        status = "ok" if check.ok else "missing" if check.required else "warn"
        print(f"[{status}] {check.name}: {check.detail}")
    if args.strict and any(check.required and not check.ok for check in checks):
        sys.exit(1)


def run_live_readiness(
    *,
    device: str,
    tts_provider: str,
    extension_dist: Path,
    artifact_dir: Path,
    live_settings: LiveSettings | None = None,
) -> list[LiveReadyCheck]:
    phase3 = run_phase3_checks(device=device, provider=tts_provider)
    phase4 = run_verification(artifact_dir=artifact_dir / "preflight")
    current_settings = (
        live_settings
        if live_settings is not None
        else _CurrentLiveSettings(
            stt_enabled=settings.stt_enabled,
            stt_provider=settings.stt_provider,
            tts_enabled=settings.tts_enabled,
            tts_playback_enabled=settings.tts_playback_enabled,
            tts_output_device=settings.tts_output_device,
        )
    )
    return [
        *_phase3_readiness_checks(phase3),
        _phase4_preflight_check(phase4.passed, phase4.artifact_path),
        *_extension_checks(extension_dist),
        *_environment_checks(current_settings),
    ]


def _phase3_readiness_checks(results: list[Phase3CheckResult]) -> list[LiveReadyCheck]:
    return [
        LiveReadyCheck(
            name=f"phase3: {result.name}",
            ok=result.ok,
            detail=result.detail,
            required=result.required,
        )
        for result in results
    ]


def _phase4_preflight_check(passed: bool, artifact_path: str | None) -> LiveReadyCheck:
    return LiveReadyCheck(
        name="phase4 local preflight",
        ok=passed,
        detail=artifact_path or "no artifact written",
    )


def _extension_checks(extension_dist: Path) -> list[LiveReadyCheck]:
    required_files = [
        extension_dist / "manifest.json",
        extension_dist / "popup.html",
        extension_dist / "sidepanel.html",
        extension_dist / "offscreen.html",
        extension_dist / "assets" / "background.js",
        extension_dist / "assets" / "offscreen.js",
        extension_dist / "assets" / "content.js",
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    return [
        LiveReadyCheck(
            name="Chrome extension build",
            ok=not missing,
            detail="ready" if not missing else "missing " + ", ".join(missing),
        )
    ]


def _environment_checks(live_settings: LiveSettings) -> list[LiveReadyCheck]:
    return [
        LiveReadyCheck(
            name="live STT enabled",
            ok=live_settings.stt_enabled,
            detail=f"PROOF_STT_ENABLED={live_settings.stt_enabled}",
        ),
        LiveReadyCheck(
            name="live STT provider",
            ok=bool(live_settings.stt_provider) and live_settings.stt_provider != "fake",
            detail=f"PROOF_STT_PROVIDER={live_settings.stt_provider}",
        ),
        LiveReadyCheck(
            name="TTS enabled",
            ok=live_settings.tts_enabled,
            detail=f"PROOF_TTS_ENABLED={live_settings.tts_enabled}",
        ),
        LiveReadyCheck(
            name="TTS playback enabled",
            ok=live_settings.tts_playback_enabled,
            detail=f"PROOF_TTS_PLAYBACK_ENABLED={live_settings.tts_playback_enabled}",
        ),
        LiveReadyCheck(
            name="TTS output device configured",
            ok=bool(live_settings.tts_output_device),
            detail=f"PROOF_TTS_OUTPUT_DEVICE={live_settings.tts_output_device or 'unset'}",
        ),
    ]


if __name__ == "__main__":
    main()
