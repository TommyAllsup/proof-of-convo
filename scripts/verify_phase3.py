from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings
from backend.tts.playback import AudioOutputDevice, list_output_devices


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check Phase 3 TTS, virtual audio, and provider readiness."
    )
    parser.add_argument(
        "--device",
        default=settings.tts_output_device or "BlackHole",
        help="Expected virtual output device name or index.",
    )
    parser.add_argument(
        "--provider",
        choices=["fake", "macos_say", "elevenlabs", "cartesia"],
        default=settings.tts_provider,
        help="Provider to validate for credential readiness.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when required checks fail.",
    )
    args = parser.parse_args()

    results = run_checks(device=args.device, provider=args.provider)
    for result in results:
        status = "ok" if result.ok else "missing" if result.required else "warn"
        print(f"[{status}] {result.name}: {result.detail}")

    failed = [result for result in results if result.required and not result.ok]
    if failed and args.strict:
        sys.exit(1)


def run_checks(*, device: str, provider: str) -> list[CheckResult]:
    output_devices = _safe_output_devices()
    device_match = find_output_device(output_devices, device)
    results = [
        CheckResult(
            name="macOS",
            ok=platform.system() == "Darwin",
            detail=platform.platform(),
        ),
        CheckResult(
            name="sounddevice output devices",
            ok=bool(output_devices),
            detail=", ".join(f"{item.index}:{item.name}" for item in output_devices) or "none",
        ),
        CheckResult(
            name="virtual mic output device",
            ok=device_match is not None,
            detail=(
                f"matched {device_match.index}:{device_match.name}"
                if device_match is not None
                else f"{device!r} not visible to PortAudio"
            ),
        ),
        CheckResult(
            name="BlackHole Homebrew cask",
            ok=_brew_cask_installed("blackhole-2ch") or _brew_cask_installed("blackhole-16ch"),
            detail=_blackhole_install_detail(),
            required=False,
        ),
        CheckResult(
            name="TTS dump directory",
            ok=_path_parent_writable(settings.tts_dump_dir),
            detail=str(settings.tts_dump_dir),
            required=False,
        ),
        _provider_check(provider),
    ]
    return results


def find_output_device(
    devices: list[AudioOutputDevice],
    expected: str,
) -> AudioOutputDevice | None:
    value = expected.strip()
    if value.isdigit():
        index = int(value)
        return next((item for item in devices if item.index == index), None)
    return next((item for item in devices if value.lower() in item.name.lower()), None)


def _safe_output_devices() -> list[AudioOutputDevice]:
    try:
        return list_output_devices()
    except Exception:
        return []


def _provider_check(provider: str) -> CheckResult:
    normalized = provider.strip().lower()
    if normalized == "fake":
        return CheckResult(
            name="TTS provider credentials",
            ok=True,
            detail="fake provider needs no credentials",
            required=False,
        )
    if normalized == "macos_say":
        return CheckResult(
            name="macOS local TTS tools",
            ok=shutil.which("say") is not None and shutil.which("afconvert") is not None,
            detail="requires built-in say and afconvert commands",
        )
    if normalized == "elevenlabs":
        ok = bool(os.getenv("ELEVENLABS_API_KEY")) and bool(settings.tts_voice_id)
        return CheckResult(
            name="ElevenLabs credentials",
            ok=ok,
            detail="ELEVENLABS_API_KEY and PROOF_TTS_VOICE_ID required",
        )
    if normalized == "cartesia":
        ok = bool(os.getenv("CARTESIA_API_KEY")) and bool(settings.tts_voice_id)
        return CheckResult(
            name="Cartesia credentials",
            ok=ok,
            detail="CARTESIA_API_KEY and PROOF_TTS_VOICE_ID required",
        )
    return CheckResult(name="TTS provider", ok=False, detail=f"unsupported provider {provider!r}")


def _brew_cask_installed(cask: str) -> bool:
    if shutil.which("brew") is None:
        return False
    result = subprocess.run(
        ["brew", "list", "--cask", cask],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _blackhole_install_detail() -> str:
    if _brew_cask_installed("blackhole-2ch"):
        return "blackhole-2ch installed"
    if _brew_cask_installed("blackhole-16ch"):
        return "blackhole-16ch installed"
    if shutil.which("brew") is not None:
        return "not installed; brew install --cask blackhole-2ch then reboot"
    return "not installed; Homebrew not found"


def _path_parent_writable(path: Path) -> bool:
    parent = path if path.exists() else path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return os.access(parent, os.W_OK)


if __name__ == "__main__":
    main()
