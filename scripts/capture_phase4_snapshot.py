from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

_urlopen = request.urlopen


@dataclass(frozen=True)
class SnapshotArtifact:
    name: str
    path: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class Phase4Snapshot:
    backend_url: str
    output_dir: str
    created_at: str
    artifacts: list[SnapshotArtifact]

    @property
    def ok(self) -> bool:
        return all(artifact.ok for artifact in self.artifacts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture Phase 4 live-validation runtime JSON snapshots from the backend."
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path(".data/phase4-live"))
    parser.add_argument("--timeout-s", type=float, default=3.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any requested backend snapshot cannot be captured.",
    )
    args = parser.parse_args()

    snapshot = capture_snapshot(
        backend_url=args.backend_url,
        output_dir=args.output_dir,
        timeout_s=args.timeout_s,
    )
    for artifact in snapshot.artifacts:
        status = "ok" if artifact.ok else "fail"
        detail = artifact.path if artifact.ok else artifact.error
        print(f"[{status}] {artifact.name}: {detail}")
    print(f"manifest={args.output_dir / 'phase4-snapshot-manifest.json'}")
    print(f"ok={snapshot.ok}")
    if args.strict and not snapshot.ok:
        raise SystemExit(1)


def capture_snapshot(
    *,
    backend_url: str,
    output_dir: Path,
    timeout_s: float = 3.0,
) -> Phase4Snapshot:
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).isoformat()
    normalized_backend_url = backend_url.rstrip("/")
    endpoints = {
        "health": "/health",
        "sessions": "/api/sessions",
        "audio_consumer": "/api/audio/consumer",
        "agent_status": "/api/agent",
        "stt_status": "/api/stt",
        "tts_status": "/api/tts",
        "agent_summary": "/api/agent/summary",
    }
    artifacts = [
        _capture_endpoint(
            backend_url=normalized_backend_url,
            endpoint_path=endpoint_path,
            output_path=output_dir / f"{name}.json",
            name=name,
            timeout_s=timeout_s,
            optional=name == "agent_summary",
        )
        for name, endpoint_path in endpoints.items()
    ]
    snapshot = Phase4Snapshot(
        backend_url=normalized_backend_url,
        output_dir=str(output_dir),
        created_at=created_at,
        artifacts=artifacts,
    )
    (output_dir / "phase4-snapshot-manifest.json").write_text(
        json.dumps(
            {
                **asdict(snapshot),
                "ok": snapshot.ok,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return snapshot


def _capture_endpoint(
    *,
    backend_url: str,
    endpoint_path: str,
    output_path: Path,
    name: str,
    timeout_s: float,
    optional: bool,
) -> SnapshotArtifact:
    url = f"{backend_url}{endpoint_path}"
    try:
        payload = _get_json(url, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001 - CLI should record backend/API failures.
        error_message = f"{type(exc).__name__}: {exc}"
        if optional:
            output_path.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "optional": True,
                        "url": url,
                        "error": error_message,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return SnapshotArtifact(name=name, path=str(output_path), ok=True, error=error_message)
        return SnapshotArtifact(name=name, path=str(output_path), ok=False, error=error_message)

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return SnapshotArtifact(name=name, path=str(output_path), ok=True)


def _get_json(url: str, *, timeout_s: float) -> dict[str, Any]:
    with _urlopen(url, timeout=timeout_s) as response:
        status = getattr(response, "status", 200)
        body = response.read()
    if status < 200 or status >= 300:
        raise RuntimeError(f"GET {url} returned HTTP {status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GET {url} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {url} returned non-object JSON")
    return payload


if __name__ == "__main__":
    try:
        main()
    except error.URLError as exc:
        raise SystemExit(f"backend request failed: {exc}") from exc
