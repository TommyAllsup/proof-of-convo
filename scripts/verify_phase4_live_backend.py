from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from urllib import request

_urlopen = request.urlopen


@dataclass(frozen=True)
class BackendHealthCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify a running backend is ready for Phase 4 live Meet validation."
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-output-device", default="BlackHole")
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    checks = verify_backend_health(
        backend_url=args.backend_url,
        expected_output_device=args.expected_output_device,
        timeout_s=args.timeout_s,
    )
    for check in checks:
        status = "ok" if check.ok else "missing" if check.required else "warn"
        print(f"[{status}] {check.name}: {check.detail}")
    if args.strict and any(check.required and not check.ok for check in checks):
        sys.exit(1)


def verify_backend_health(
    *,
    backend_url: str,
    expected_output_device: str,
    timeout_s: float = 3.0,
) -> list[BackendHealthCheck]:
    try:
        health = _get_json(f"{backend_url.rstrip('/')}/health", timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001 - CLI should report backend connection failures.
        return [
            BackendHealthCheck(
                name="backend health endpoint",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            )
        ]
    return checks_from_health(health, expected_output_device=expected_output_device)


def checks_from_health(
    health: dict[str, object],
    *,
    expected_output_device: str,
) -> list[BackendHealthCheck]:
    audio_consumer = _dict_value(health.get("audio_consumer"))
    stt_worker = _dict_value(health.get("stt_worker"))
    tts_worker = _dict_value(health.get("tts_worker"))
    agent = _dict_value(health.get("agent"))
    readiness = _dict_value(agent.get("readiness"))
    output_device = str(tts_worker.get("output_device") or "")
    expected = expected_output_device.strip().lower()
    return [
        BackendHealthCheck(
            name="backend health endpoint",
            ok=health.get("ok") is True,
            detail=f"ok={health.get('ok')}",
        ),
        BackendHealthCheck(
            name="audio consumer running",
            ok=audio_consumer.get("running") is True,
            detail=f"running={audio_consumer.get('running')}",
        ),
        BackendHealthCheck(
            name="live STT worker enabled",
            ok=stt_worker.get("enabled") is True,
            detail=f"enabled={stt_worker.get('enabled')}",
        ),
        BackendHealthCheck(
            name="live STT worker running",
            ok=stt_worker.get("running") is True,
            detail=f"running={stt_worker.get('running')}",
        ),
        BackendHealthCheck(
            name="live STT provider",
            ok=bool(stt_worker.get("provider")) and stt_worker.get("provider") != "fake",
            detail=f"provider={stt_worker.get('provider')}",
        ),
        BackendHealthCheck(
            name="TTS worker enabled",
            ok=tts_worker.get("enabled") is True,
            detail=f"enabled={tts_worker.get('enabled')}",
        ),
        BackendHealthCheck(
            name="TTS worker running",
            ok=tts_worker.get("running") is True,
            detail=f"running={tts_worker.get('running')}",
        ),
        BackendHealthCheck(
            name="TTS playback enabled",
            ok=tts_worker.get("playback_enabled") is True,
            detail=f"playback_enabled={tts_worker.get('playback_enabled')}",
        ),
        BackendHealthCheck(
            name="TTS output device",
            ok=bool(output_device) and expected in output_device.lower(),
            detail=f"output_device={output_device or 'unset'}",
        ),
        BackendHealthCheck(
            name="agent readiness reflects capture state",
            ok="capture inactive" in _string_list(readiness.get("blockers"))
            or readiness.get("can_auto_speak") is True,
            detail=(
                f"can_auto_speak={readiness.get('can_auto_speak')} "
                f"blockers={readiness.get('blockers')}"
            ),
            required=False,
        ),
    ]


def _get_json(url: str, *, timeout_s: float) -> dict[str, object]:
    with _urlopen(url, timeout=timeout_s) as response:
        status = getattr(response, "status", 200)
        body = response.read()
    if status < 200 or status >= 300:
        raise RuntimeError(f"GET {url} returned HTTP {status}")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"GET {url} returned non-object JSON")
    return value


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


if __name__ == "__main__":
    main()
