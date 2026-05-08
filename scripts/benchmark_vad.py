from __future__ import annotations

import argparse
import json
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from backend.audio.frames import AudioPacket, audio_levels, pcm16_to_float32
from backend.audio.manager import AudioChunkEvent
from backend.audio.vad import create_vad_provider


@dataclass(frozen=True)
class ProviderBenchmark:
    provider: str
    files: int
    duration_s: float
    wall_time_s: float
    real_time_factor: float
    segment_count: int
    speech_duration_s: float
    speech_ratio: float
    starts_per_minute: float
    segment_min_s: float
    segment_p50_s: float
    segment_p95_s: float
    segment_max_s: float
    processing_errors: int


def _read_chunks(path: Path, chunk_ms: int) -> list[bytes]:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != 16_000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16 kHz mono PCM16 WAV")
        frames_per_chunk = wav.getframerate() * chunk_ms // 1000
        chunks: list[bytes] = []
        while True:
            chunk = wav.readframes(frames_per_chunk)
            if not chunk:
                return chunks
            chunks.append(chunk)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def run_provider(provider_name: str, files: list[Path], chunk_ms: int) -> ProviderBenchmark:
    provider = create_vad_provider(provider_name)
    started = time.perf_counter()
    duration_s = 0.0
    starts = 0
    errors = 0
    segment_durations_s: list[float] = []

    for path in files:
        session_id = path.stem
        chunks = _read_chunks(path, chunk_ms)
        file_started_at_ms = duration_s * 1000.0
        for sequence, pcm16 in enumerate(chunks):
            sample_count = len(pcm16) // 2
            chunk_started_at_ms = file_started_at_ms + sequence * chunk_ms
            packet = AudioPacket(
                sequence=sequence,
                tab_id=0,
                capture_started_at_ms=file_started_at_ms,
                chunk_started_at_ms=chunk_started_at_ms,
                client_sent_at_ms=chunk_started_at_ms,
                sample_rate=16_000,
                sample_count=sample_count,
                pcm16=pcm16,
            )
            rms, peak = audio_levels(pcm16_to_float32(pcm16))
            event = AudioChunkEvent(
                session_id=session_id,
                packet=packet,
                rms=rms,
                peak=peak,
                received_at_ms=chunk_started_at_ms,
            )
            duration_s += packet.duration_ms / 1000.0
            try:
                endpoint_events = provider.process(event)
            except Exception:
                errors += 1
                continue
            for endpoint_event in endpoint_events:
                if endpoint_event.type == "speech_start":
                    starts += 1
                if endpoint_event.segment is not None:
                    segment_durations_s.append(endpoint_event.segment.duration_ms / 1000.0)

        flushed = provider.flush(session_id)
        if flushed is not None:
            segment_durations_s.append(flushed.duration_ms / 1000.0)

    wall_time_s = time.perf_counter() - started
    speech_duration_s = sum(segment_durations_s)
    return ProviderBenchmark(
        provider=provider.name,
        files=len(files),
        duration_s=duration_s,
        wall_time_s=wall_time_s,
        real_time_factor=wall_time_s / duration_s if duration_s else 0.0,
        segment_count=len(segment_durations_s),
        speech_duration_s=speech_duration_s,
        speech_ratio=speech_duration_s / duration_s if duration_s else 0.0,
        starts_per_minute=starts / (duration_s / 60.0) if duration_s else 0.0,
        segment_min_s=min(segment_durations_s, default=0.0),
        segment_p50_s=_percentile(segment_durations_s, 0.50),
        segment_p95_s=_percentile(segment_durations_s, 0.95),
        segment_max_s=max(segment_durations_s, default=0.0),
        processing_errors=errors,
    )


def _with_deltas(results: list[ProviderBenchmark]) -> list[dict[str, object]]:
    baseline = next((result for result in results if result.provider == "rms"), None)
    rows: list[dict[str, object]] = []
    for result in results:
        row: dict[str, object] = asdict(result)
        row["rms_comparison_delta"] = {
            "segment_count": result.segment_count - baseline.segment_count if baseline else None,
            "speech_duration_s": result.speech_duration_s - baseline.speech_duration_s
            if baseline
            else None,
            "speech_ratio": result.speech_ratio - baseline.speech_ratio if baseline else None,
            "starts_per_minute": result.starts_per_minute - baseline.starts_per_minute
            if baseline
            else None,
        }
        rows.append(row)
    return rows


def _markdown(rows: list[dict[str, object]], files: list[Path]) -> str:
    lines = [
        "# Phase 2 VAD Benchmark",
        "",
        f"Input files: {len(files)}",
        "",
        (
            "| Provider | Duration s | Wall s | RTF | Segments | Speech s | Speech % | "
            "Starts/min | Segment p50 s | Segment p95 s | Errors | Delta segments | "
            "Delta speech s |"
        ),
        (
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: |"
        ),
    ]
    for row in rows:
        values = cast(dict[str, Any], row)
        delta = cast(dict[str, Any], values["rms_comparison_delta"])
        provider = str(values["provider"])
        duration_s = float(values["duration_s"])
        wall_time_s = float(values["wall_time_s"])
        real_time_factor = float(values["real_time_factor"])
        segment_count = int(values["segment_count"])
        speech_duration_s = float(values["speech_duration_s"])
        speech_ratio = float(values["speech_ratio"])
        starts_per_minute = float(values["starts_per_minute"])
        segment_p50_s = float(values["segment_p50_s"])
        segment_p95_s = float(values["segment_p95_s"])
        processing_errors = int(values["processing_errors"])
        delta_speech = delta["speech_duration_s"]
        delta_segment = delta["segment_count"]
        delta_segment_text = str(delta_segment) if delta_segment is not None else "--"
        delta_speech_text = f"{float(delta_speech):.2f}" if delta_speech is not None else "--"
        lines.append(
            f"| {provider} | {duration_s:.2f} | {wall_time_s:.2f} | "
            f"{real_time_factor:.4f} | {segment_count} | {speech_duration_s:.2f} | "
            f"{speech_ratio:.2%} | {starts_per_minute:.2f} | {segment_p50_s:.2f} | "
            f"{segment_p95_s:.2f} | {processing_errors} | {delta_segment_text} | "
            f"{delta_speech_text} |"
        )
    lines.extend(["", "## Files", ""])
    lines.extend(f"- `{path}`" for path in files)
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay local WAV captures through VAD providers.")
    parser.add_argument(
        "--provider",
        action="append",
        choices=["rms", "silero_onnx"],
        required=True,
    )
    parser.add_argument("--input-glob", default=".data/audio/*_first_3600s.wav")
    parser.add_argument("--chunk-ms", type=int, default=200)
    parser.add_argument("--output", required=True)
    parser.add_argument("--json-output")
    args = parser.parse_args()

    files = sorted(Path().glob(args.input_glob))
    if not files:
        raise SystemExit(f"no input files matched {args.input_glob}")

    results = [run_provider(provider, files, args.chunk_ms) for provider in args.provider]
    rows = _with_deltas(results)
    payload = {"files": [str(path) for path in files], "results": rows}

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix == ".json":
        output.write_text(json.dumps(payload, indent=2) + "\n")
    else:
        output.write_text(_markdown(rows, files))

    if args.json_output:
        Path(args.json_output).write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
