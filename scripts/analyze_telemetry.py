from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.audio.endpointing import RmsEndpointDetector
from backend.audio.frames import AudioPacket
from backend.audio.manager import AudioChunkEvent


@dataclass(frozen=True)
class TelemetrySummary:
    chunks_path: Path
    session_id: str
    total_chunks: int
    duration_s: float
    dropped_chunks: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_max_ms: float | None
    rms_p50: float
    rms_p95: float
    peak_max: float
    speech_segments: int
    speech_duration_s: float
    speech_ratio: float


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _iter_chunks(chunks_path: Path) -> Iterable[dict[str, Any]]:
    with chunks_path.open(encoding="utf-8") as chunks_file:
        for line in chunks_file:
            if line.strip():
                yield json.loads(line)


def _event_from_payload(payload: dict[str, Any]) -> AudioChunkEvent:
    sample_rate = int(payload["sample_rate"])
    sample_count = int(payload["sample_count"])
    packet = AudioPacket(
        sequence=int(payload["sequence"]),
        tab_id=int(payload["tab_id"]) if payload.get("tab_id") is not None else 0,
        capture_started_at_ms=0.0,
        chunk_started_at_ms=float(payload["chunk_started_at_ms"]),
        client_sent_at_ms=float(payload["client_sent_at_ms"] or 0.0),
        sample_rate=sample_rate,
        sample_count=sample_count,
        pcm16=b"\0" * sample_count * 2,
    )
    return AudioChunkEvent(
        session_id=str(payload["session_id"]),
        packet=packet,
        rms=float(payload["rms"]),
        peak=float(payload["peak"]),
        received_at_ms=float(payload["received_at_ms"]),
    )


def summarize_chunks(
    chunks_path: Path,
    *,
    speech_rms_threshold: float,
    silence_ms: float,
    min_speech_ms: float,
) -> TelemetrySummary:
    detector = RmsEndpointDetector(
        speech_rms_threshold=speech_rms_threshold,
        silence_ms=silence_ms,
        min_speech_ms=min_speech_ms,
    )
    session_id = ""
    total_chunks = 0
    first_chunk_ms: float | None = None
    last_chunk_end_ms: float | None = None
    last_dropped_chunks = 0
    latencies: list[float] = []
    rms_values: list[float] = []
    peaks: list[float] = []
    speech_durations: list[float] = []

    for payload in _iter_chunks(chunks_path):
        event = _event_from_payload(payload)
        session_id = event.session_id
        total_chunks += 1
        chunk_end_ms = event.packet.chunk_started_at_ms + event.packet.duration_ms
        first_chunk_ms = (
            event.packet.chunk_started_at_ms if first_chunk_ms is None else first_chunk_ms
        )
        last_chunk_end_ms = chunk_end_ms
        last_dropped_chunks = int(payload["dropped_chunks"])
        if payload.get("latency_ms") is not None:
            latencies.append(float(payload["latency_ms"]))
        rms_values.append(event.rms)
        peaks.append(event.peak)

        for endpoint in detector.process(event):
            if endpoint.segment is not None:
                speech_durations.append(endpoint.segment.duration_ms)

    if session_id:
        flushed = detector.flush(session_id)
        if flushed is not None:
            speech_durations.append(flushed.duration_ms)

    duration_s = 0.0
    if first_chunk_ms is not None and last_chunk_end_ms is not None:
        duration_s = max(0.0, (last_chunk_end_ms - first_chunk_ms) / 1000.0)

    speech_duration_s = sum(speech_durations) / 1000.0
    return TelemetrySummary(
        chunks_path=chunks_path,
        session_id=session_id,
        total_chunks=total_chunks,
        duration_s=duration_s,
        dropped_chunks=last_dropped_chunks,
        latency_p50_ms=statistics.median(latencies) if latencies else None,
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_max_ms=max(latencies) if latencies else None,
        rms_p50=statistics.median(rms_values) if rms_values else 0.0,
        rms_p95=_percentile(rms_values, 0.95) or 0.0,
        peak_max=max(peaks) if peaks else 0.0,
        speech_segments=len(speech_durations),
        speech_duration_s=speech_duration_s,
        speech_ratio=speech_duration_s / duration_s if duration_s > 0 else 0.0,
    )


def _format_optional_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def render_markdown(summaries: list[TelemetrySummary]) -> str:
    lines = [
        "# Capture Telemetry Summary",
        "",
        "| Session | Duration | Chunks | Drops | Latency p50/p95/max ms | "
        "RMS p50/p95 | Peak max | Speech segments | Speech time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        lines.append(
            "| "
            f"`{summary.session_id[:8]}` | "
            f"{summary.duration_s / 60:.1f} min | "
            f"{summary.total_chunks} | "
            f"{summary.dropped_chunks} | "
            f"{_format_optional_ms(summary.latency_p50_ms)}/"
            f"{_format_optional_ms(summary.latency_p95_ms)}/"
            f"{_format_optional_ms(summary.latency_max_ms)} | "
            f"{summary.rms_p50:.4f}/{summary.rms_p95:.4f} | "
            f"{summary.peak_max:.4f} | "
            f"{summary.speech_segments} | "
            f"{summary.speech_duration_s / 60:.1f} min ({summary.speech_ratio:.0%}) |"
        )
    lines.extend(
        [
            "",
            "Speech time is estimated with the repo's baseline RMS endpoint detector. It is a",
            "calibration aid, not a diarization or speech-recognition result.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize capture telemetry JSONL files.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Telemetry *_chunks.jsonl files. Defaults to .data/telemetry/*_chunks.jsonl.",
    )
    parser.add_argument("--threshold", type=float, default=0.012)
    parser.add_argument("--silence-ms", type=float, default=500.0)
    parser.add_argument("--min-speech-ms", type=float, default=250.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    paths = args.paths or sorted(Path(".data/telemetry").glob("*_chunks.jsonl"))
    summaries = [
        summarize_chunks(
            path,
            speech_rms_threshold=args.threshold,
            silence_ms=args.silence_ms,
            min_speech_ms=args.min_speech_ms,
        )
        for path in paths
    ]
    rendered = render_markdown(summaries)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
