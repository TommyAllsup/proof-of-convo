from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings


@dataclass(frozen=True)
class LiveRunbookConfig:
    meeting_url: str
    tester: str
    backend_url: str
    backend_host: str
    backend_port: int
    vad_provider: str
    diarization_provider: str
    stt_provider: str
    stt_model: str
    stt_language: str | None
    tts_provider: str
    tts_model: str | None
    tts_voice_name: str
    tts_output_device: str
    preflight_dir: str
    live_output_dir: str
    latency_ms: int


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write a machine-specific Phase 4 live Google Meet validation runbook."
    )
    parser.add_argument("--meeting-url", default="https://meet.google.com/...")
    parser.add_argument("--tester", default="$USER")
    parser.add_argument("--backend-url", default=f"http://{settings.host}:{settings.port}")
    parser.add_argument("--output", type=Path, default=Path(".data/phase4-live-runbook.md"))
    parser.add_argument("--preflight-dir", default=".data/phase4-preflight")
    parser.add_argument("--live-output-dir", default=".data/phase4-live")
    parser.add_argument("--latency-ms", type=int, default=1500)
    args = parser.parse_args()

    config = LiveRunbookConfig(
        meeting_url=args.meeting_url,
        tester=args.tester,
        backend_url=args.backend_url,
        backend_host=settings.host,
        backend_port=settings.port,
        vad_provider=settings.vad_provider,
        diarization_provider=settings.diarization_provider,
        stt_provider=settings.stt_provider,
        stt_model=settings.stt_model or "mlx-community/whisper-large-v3-turbo",
        stt_language=settings.stt_language,
        tts_provider=settings.tts_provider,
        tts_model=settings.tts_model,
        tts_voice_name=settings.tts_voice_name,
        tts_output_device=settings.tts_output_device or "BlackHole 2ch",
        preflight_dir=args.preflight_dir,
        live_output_dir=args.live_output_dir,
        latency_ms=args.latency_ms,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_runbook(config), encoding="utf-8")
    print(f"runbook={args.output}")


def render_runbook(config: LiveRunbookConfig) -> str:
    stt_language = config.stt_language or "auto"
    tts_model = config.tts_model or "provider default"
    preflight_json = f"{config.preflight_dir}/phase-4-preflight.json"
    return "\n".join(
        [
            "# Phase 4 Live Google Meet Validation Runbook",
            "",
            "## Target",
            "",
            f"- Meeting URL: `{config.meeting_url}`",
            f"- Tester: `{config.tester}`",
            f"- Backend URL: `{config.backend_url}`",
            "",
            "## Configuration Notes",
            "",
            *_configuration_notes(config),
            "",
            "## Backend Environment",
            "",
            "```bash",
            f"PROOF_BACKEND_HOST={config.backend_host}",
            f"PROOF_BACKEND_PORT={config.backend_port}",
            f"PROOF_VAD_PROVIDER={config.vad_provider}",
            f"PROOF_DIARIZATION_PROVIDER={config.diarization_provider}",
            "PROOF_STT_ENABLED=true",
            f"PROOF_STT_PROVIDER={config.stt_provider}",
            f"PROOF_STT_MODEL={config.stt_model}",
            f"PROOF_STT_LANGUAGE={stt_language}",
            "PROOF_TTS_ENABLED=true",
            f"PROOF_TTS_PROVIDER={config.tts_provider}",
            f"PROOF_TTS_MODEL={tts_model}",
            f"PROOF_TTS_VOICE_NAME={config.tts_voice_name}",
            "PROOF_TTS_PLAYBACK_ENABLED=true",
            f"PROOF_TTS_OUTPUT_DEVICE={config.tts_output_device}",
            "uv run backend",
            "```",
            "",
            "## Preflight",
            "",
            "```bash",
            "npm --prefix extension run build",
            f"uv run verify-phase4 --strict --artifact-dir {config.preflight_dir}",
            "uv run verify-phase4-live-ready --strict",
            "```",
            "",
            "## Backend Launch Check",
            "",
            "Start the backend with the environment above, then verify the running process before",
            "joining Meet:",
            "",
            "```bash",
            f"uv run verify-phase4-live-backend --backend-url {config.backend_url} \\",
            f"  --expected-output-device {config.tts_output_device} \\",
            "  --strict",
            "```",
            "",
            "## Meet Setup",
            "",
            "- Load `extension/dist` as an unpacked Chrome extension.",
            "- Join the meeting URL in Chrome.",
            f"- Set the Google Meet microphone to `{config.tts_output_device}`.",
            "- Start capture from the extension sidebar or popup.",
            "- Keep hardware speakers muted or use headphones to avoid feedback.",
            "",
            "## Live Checks",
            "",
            "- Confirm `/api/sessions` shows an active Meet capture session.",
            "- Confirm `/api/stt` shows completed transcripts while another participant speaks.",
            "- Switch Erica to `assistant` mode and directly ask Erica a short question.",
            "- Confirm another participant hears Erica through the Meet audio path.",
            "- Switch Erica to `facilitator` and verify one safe-gap clarifying question.",
            "- End the meeting from the sidebar or by saying `Erica, end meeting`.",
            "",
            "## Evidence Bundle",
            "",
            "```bash",
            "uv run phase4-live-bundle \\",
            f"  --backend-url {config.backend_url} \\",
            f"  --meeting-url {config.meeting_url} \\",
            f"  --tester {config.tester} \\",
            f"  --output-dir {config.live_output_dir} \\",
            f"  --preflight-json {preflight_json} \\",
            "  --capture-active \\",
            "  --transcript-visible \\",
            "  --direct-answer-audible \\",
            "  --facilitator-auto-speak-observed \\",
            "  --summary-generated \\",
            "  --provider-telemetry-visible \\",
            "  --no-feedback-loop \\",
            f"  --median-response-latency-ms {config.latency_ms} \\",
            "  --strict",
            "```",
            "",
            "## Completion Evidence",
            "",
            "- `verify-phase4-live-ready --strict` passed before the Meet run.",
            "- `verify-phase4-live-backend --strict` passed after backend startup.",
            "- `phase4-live-bundle --strict` passed after the Meet run.",
            "- The generated report links health, sessions, audio consumer, agent, STT, TTS, and",
            "  summary artifacts.",
            "- The report notes any latency, interruption, or feedback-loop observations.",
            "",
        ]
    )


def _configuration_notes(config: LiveRunbookConfig) -> list[str]:
    notes: list[str] = []
    if config.tts_provider == "fake":
        notes.append(
            "- `PROOF_TTS_PROVIDER=fake` generates synthetic audio for routing tests. Use "
            "`macos_say`, `elevenlabs`, or `cartesia` for a more realistic audible Meet run."
        )
    if config.tts_output_device.lower() in {"blackhole", "blackhole 2ch"}:
        notes.append(
            "- Confirm the exact PortAudio output device name matches "
            f"`{config.tts_output_device}` before starting the backend."
        )
    if config.vad_provider == "rms":
        notes.append(
            "- `PROOF_VAD_PROVIDER=rms` is lightweight; use `silero_onnx` for the intended live "
            "validation path when local dependencies are available."
        )
    return notes or ["- Current configuration is ready for the generated live-validation steps."]


if __name__ == "__main__":
    main()
