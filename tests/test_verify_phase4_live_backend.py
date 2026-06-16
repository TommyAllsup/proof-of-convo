from __future__ import annotations

from scripts.verify_phase4_live_backend import checks_from_health


def test_live_backend_checks_pass_for_enabled_workers() -> None:
    checks = checks_from_health(_health(), expected_output_device="BlackHole")

    required = [check for check in checks if check.required]
    assert all(check.ok for check in required)
    assert checks[-1].name == "agent readiness reflects capture state"
    assert checks[-1].ok is True


def test_live_backend_checks_fail_closed_for_disabled_playback() -> None:
    health = _health()
    health["stt_worker"]["provider"] = "fake"  # type: ignore[index]
    health["tts_worker"]["playback_enabled"] = False  # type: ignore[index]
    health["tts_worker"]["output_device"] = "Mac mini Speakers"  # type: ignore[index]

    checks = checks_from_health(health, expected_output_device="BlackHole")
    by_name = {check.name: check for check in checks}

    assert by_name["live STT provider"].ok is False
    assert by_name["TTS playback enabled"].ok is False
    assert by_name["TTS output device"].ok is False


def _health() -> dict[str, object]:
    return {
        "ok": True,
        "audio_consumer": {"running": True},
        "stt_worker": {
            "enabled": True,
            "running": True,
            "provider": "mlx_whisper",
        },
        "tts_worker": {
            "enabled": True,
            "running": True,
            "playback_enabled": True,
            "output_device": "BlackHole 2ch",
        },
        "agent": {
            "readiness": {
                "can_auto_speak": False,
                "blockers": ["capture inactive"],
            }
        },
    }
