from __future__ import annotations

import argparse
import json
import platform
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from backend.audio.stt import SttTranscript, create_stt_provider
from backend.audio.stt_windows import (
    UtteranceWindow,
    extract_windows,
    wav_metadata,
    write_windows_jsonl,
)


@dataclass(frozen=True)
class SttBenchmarkSummary:
    vad_provider: str
    stt_provider: str
    model_id: str
    files: int
    source_audio_duration_s: float
    utterance_windows: int
    transcribed_speech_duration_s: float
    stt_wall_time_s: float
    model_load_time_s: float | None
    real_time_factor: float
    window_wall_p50_s: float
    window_wall_p95_s: float
    empty_transcript_rate: float
    error_count: int
    artifact_dir: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def run_benchmark(
    *,
    files: list[Path],
    vad_provider: str,
    stt_provider_name: str,
    model_id: str | None,
    language: str | None,
    artifact_dir: Path,
    limit_segments: int | None,
    max_audio_minutes: float | None,
    chunk_ms: int,
    pre_roll_ms: float,
    post_roll_ms: float,
) -> dict[str, Any]:
    selected_files = _limit_files_by_audio(files, max_audio_minutes)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    windows = extract_windows(
        selected_files,
        vad_provider_name=vad_provider,
        chunk_ms=chunk_ms,
        pre_roll_ms=pre_roll_ms,
        post_roll_ms=post_roll_ms,
    )
    if limit_segments is not None:
        windows = windows[:limit_segments]
    extraction_wall_time_s = time.perf_counter() - started

    windows_path = artifact_dir / "utterance-windows.jsonl"
    transcripts_path = artifact_dir / "transcripts.jsonl"
    write_windows_jsonl(windows, windows_path)

    stt_provider = create_stt_provider(stt_provider_name, model_id=model_id, language=language)
    model_load_time_s = stt_provider.prepare()
    transcripts: list[SttTranscript] = []
    stt_started = time.perf_counter()
    with transcripts_path.open("w", encoding="utf-8") as handle:
        for window in windows:
            transcript = stt_provider.transcribe(window)
            transcripts.append(transcript)
            handle.write(json.dumps(_transcript_record(window, transcript), sort_keys=True) + "\n")
    stt_wall_time_s = time.perf_counter() - stt_started

    joined_paths = _write_joined_transcripts(windows, transcripts, artifact_dir)
    summary = _summary(
        files=selected_files,
        vad_provider=vad_provider,
        windows=windows,
        transcripts=transcripts,
        stt_provider=stt_provider_name,
        model_id=stt_provider.model_info.model_id,
        artifact_dir=artifact_dir,
        stt_wall_time_s=stt_wall_time_s,
        model_load_time_s=model_load_time_s,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "machine": _machine_metadata(),
        "model": stt_provider.model_info.to_record(),
        "settings": {
            "chunk_ms": chunk_ms,
            "pre_roll_ms": pre_roll_ms,
            "post_roll_ms": post_roll_ms,
            "limit_segments": limit_segments,
            "max_audio_minutes": max_audio_minutes,
        },
        "input_files": [str(path) for path in selected_files],
        "artifacts": {
            "artifact_dir": str(artifact_dir),
            "windows_jsonl": str(windows_path),
            "transcripts_jsonl": str(transcripts_path),
            "joined_transcripts": [str(path) for path in joined_paths],
        },
        "extraction_wall_time_s": extraction_wall_time_s,
        "summary": summary.to_record(),
    }


def _limit_files_by_audio(files: list[Path], max_audio_minutes: float | None) -> list[Path]:
    if max_audio_minutes is None:
        return files
    selected: list[Path] = []
    remaining_s = max_audio_minutes * 60.0
    for path in files:
        sample_rate, frames = wav_metadata(path)
        duration_s = frames / sample_rate
        if remaining_s <= 0:
            break
        selected.append(path)
        remaining_s -= duration_s
    return selected


def _summary(
    *,
    files: list[Path],
    vad_provider: str,
    windows: list[UtteranceWindow],
    transcripts: list[SttTranscript],
    stt_provider: str,
    model_id: str,
    artifact_dir: Path,
    stt_wall_time_s: float,
    model_load_time_s: float | None,
) -> SttBenchmarkSummary:
    source_audio_duration_s = 0.0
    for path in files:
        sample_rate, frames = wav_metadata(path)
        source_audio_duration_s += frames / sample_rate

    speech_duration_s = sum(window.padded_duration_ms for window in windows) / 1000.0
    window_wall_times = [transcript.wall_time_s for transcript in transcripts]
    empty_count = sum(1 for transcript in transcripts if not transcript.text.strip())
    error_count = sum(1 for transcript in transcripts if transcript.error is not None)
    return SttBenchmarkSummary(
        vad_provider=vad_provider,
        stt_provider=stt_provider,
        model_id=model_id,
        files=len(files),
        source_audio_duration_s=source_audio_duration_s,
        utterance_windows=len(windows),
        transcribed_speech_duration_s=speech_duration_s,
        stt_wall_time_s=stt_wall_time_s,
        model_load_time_s=model_load_time_s,
        real_time_factor=stt_wall_time_s / speech_duration_s if speech_duration_s else 0.0,
        window_wall_p50_s=_percentile(window_wall_times, 0.50),
        window_wall_p95_s=_percentile(window_wall_times, 0.95),
        empty_transcript_rate=empty_count / len(transcripts) if transcripts else 0.0,
        error_count=error_count,
        artifact_dir=str(artifact_dir),
    )


def _write_joined_transcripts(
    windows: list[UtteranceWindow],
    transcripts: list[SttTranscript],
    artifact_dir: Path,
) -> list[Path]:
    by_session: dict[str, list[tuple[UtteranceWindow, SttTranscript]]] = defaultdict(list)
    for window, transcript in zip(windows, transcripts, strict=True):
        by_session[window.session_id].append((window, transcript))

    paths: list[Path] = []
    for session_id, rows in by_session.items():
        path = artifact_dir / f"{_safe_name(session_id)}-transcript.md"
        lines = [f"# STT Transcript: {session_id}", ""]
        for window, transcript in rows:
            start_s = window.start_ms / 1000.0
            end_s = window.end_ms / 1000.0
            text = transcript.text.strip() or "[empty]"
            error = f" error={transcript.error}" if transcript.error else ""
            lines.append(f"- `{start_s:.2f}s-{end_s:.2f}s` {text}{error}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _transcript_record(window: UtteranceWindow, transcript: SttTranscript) -> dict[str, Any]:
    record = transcript.to_record()
    record["window"] = window.to_record()
    return record


def _markdown(payload: dict[str, Any]) -> str:
    summary = cast(dict[str, Any], payload["summary"])
    artifacts = cast(dict[str, Any], payload["artifacts"])
    machine = cast(dict[str, Any], payload["machine"])
    model = cast(dict[str, Any], payload["model"])
    settings = cast(dict[str, Any], payload["settings"])
    lines = [
        "# Phase 2A STT Benchmark",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| VAD provider | {summary['vad_provider']} |",
        f"| STT provider | {summary['stt_provider']} |",
        f"| Model | {summary['model_id']} |",
        f"| Files | {summary['files']} |",
        f"| Source audio s | {float(summary['source_audio_duration_s']):.2f} |",
        f"| Utterance windows | {summary['utterance_windows']} |",
        f"| Transcribed speech s | {float(summary['transcribed_speech_duration_s']):.2f} |",
        _model_load_markdown_row(summary["model_load_time_s"]),
        f"| STT wall s | {float(summary['stt_wall_time_s']):.2f} |",
        f"| RTF | {float(summary['real_time_factor']):.4f} |",
        f"| Window wall p50 s | {float(summary['window_wall_p50_s']):.4f} |",
        f"| Window wall p95 s | {float(summary['window_wall_p95_s']):.4f} |",
        f"| Empty transcript rate | {float(summary['empty_transcript_rate']):.2%} |",
        f"| Errors | {summary['error_count']} |",
        "",
        "## Artifacts",
        "",
        f"- Artifact dir: `{artifacts['artifact_dir']}`",
        f"- Windows JSONL: `{artifacts['windows_jsonl']}`",
        f"- Transcripts JSONL: `{artifacts['transcripts_jsonl']}`",
    ]
    for path in cast(list[str], artifacts["joined_transcripts"]):
        lines.append(f"- Joined transcript: `{path}`")
    lines.extend(
        [
            "",
            "## Model Metadata",
            "",
            f"- Provider: `{model['provider']}`",
            f"- Model ID: `{model['model_id']}`",
            f"- Package: `{model.get('package')}`",
            f"- Package version: `{model.get('package_version')}`",
            f"- Quantization: `{model.get('quantization')}`",
            "",
            "## Machine",
            "",
            f"- Platform: `{machine['platform']}`",
            f"- Python: `{machine['python']}`",
            f"- Machine: `{machine['machine']}`",
            "",
            "## Settings",
            "",
            f"- Chunk ms: `{settings['chunk_ms']}`",
            f"- Pre-roll ms: `{settings['pre_roll_ms']}`",
            f"- Post-roll ms: `{settings['post_roll_ms']}`",
            f"- Limit segments: `{settings['limit_segments']}`",
            f"- Max audio minutes: `{settings['max_audio_minutes']}`",
            "",
            "## Input Files",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path in cast(list[str], payload["input_files"]))
    lines.append("")
    return "\n".join(lines)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def _model_load_markdown_row(value: object) -> str:
    if not isinstance(value, int | float):
        return "| Model load s | unavailable |"
    return f"| Model load s | {float(value):.2f} |"


def _machine_metadata() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay VAD windows through an offline STT provider."
    )
    parser.add_argument("--vad-provider", default="silero_onnx", choices=["rms", "silero_onnx"])
    parser.add_argument("--stt-provider", required=True, choices=["fake", "mlx_whisper"])
    parser.add_argument("--model-id")
    parser.add_argument("--language")
    parser.add_argument("--input-glob", default=".data/audio/*_first_3600s.wav")
    parser.add_argument("--artifact-dir", default=".data/stt/latest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--json-output")
    parser.add_argument("--limit-segments", type=int)
    parser.add_argument("--max-audio-minutes", type=float)
    parser.add_argument("--chunk-ms", type=int, default=200)
    parser.add_argument("--pre-roll-ms", type=float, default=150.0)
    parser.add_argument("--post-roll-ms", type=float, default=250.0)
    args = parser.parse_args()

    files = sorted(Path().glob(args.input_glob))
    if not files:
        raise SystemExit(f"no input files matched {args.input_glob}")

    payload = run_benchmark(
        files=files,
        vad_provider=args.vad_provider,
        stt_provider_name=args.stt_provider,
        model_id=args.model_id,
        language=args.language,
        artifact_dir=Path(args.artifact_dir),
        limit_segments=args.limit_segments,
        max_audio_minutes=args.max_audio_minutes,
        chunk_ms=args.chunk_ms,
        pre_roll_ms=args.pre_roll_ms,
        post_roll_ms=args.post_roll_ms,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix == ".json":
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        output.write_text(_markdown(payload), encoding="utf-8")

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
