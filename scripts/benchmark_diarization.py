from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DiarizationRow:
    session_id: str
    utterance_id: str
    predicted_speaker: str
    reference_speaker: str | None
    confidence: float | None
    provider: str | None
    merge_state: str | None
    text: str


@dataclass(frozen=True)
class DiarizationSummary:
    rows: int
    labeled_rows: int
    sessions: int
    predicted_speakers: int
    reference_speakers: int
    provider_counts: dict[str, int]
    merge_state_counts: dict[str, int]
    mean_confidence: float | None
    speaker_consistency: float | None
    diarization_error_proxy: float | None
    unlabeled_churn_rate: float | None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark diarization consistency from /api/stt JSON snapshots "
            "or JSONL transcript rows."
        )
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/benchmarks/diarization-benchmark.md"),
    )
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args()

    payload = run_benchmark(inputs=args.inputs)
    output = args.output
    json_output = args.json_output or output.with_suffix(".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(payload), encoding="utf-8")
    json_output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    summary = payload["summary"]
    print(
        "rows={rows} labeled={labeled_rows} consistency={consistency}".format(
            rows=summary["rows"],
            labeled_rows=summary["labeled_rows"],
            consistency=_format_optional(summary["speaker_consistency"]),
        )
    )
    print(f"markdown={output}")
    print(f"json={json_output}")


def run_benchmark(*, inputs: list[Path]) -> dict[str, Any]:
    rows: list[DiarizationRow] = []
    for path in inputs:
        rows.extend(load_rows(path))
    summary = summarize_rows(rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_files": [str(path) for path in inputs],
        "summary": asdict(summary),
        "per_reference_speaker": _per_reference_speaker(rows),
        "per_session": _per_session(rows),
    }


def load_rows(path: Path) -> list[DiarizationRow]:
    if path.suffix.lower() == ".jsonl":
        rows: list[DiarizationRow] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                row = _row_from_record(value)
                if row is not None:
                    rows.append(row)
        return rows

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("recent_transcripts"), list):
        return [
            row
            for item in value["recent_transcripts"]
            if isinstance(item, dict)
            for row in [_row_from_record(item)]
            if row is not None
        ]
    row = _row_from_record(value)
    return [row] if row is not None else []


def summarize_rows(rows: list[DiarizationRow]) -> DiarizationSummary:
    labeled = [row for row in rows if row.reference_speaker]
    confidences = [row.confidence for row in rows if row.confidence is not None]
    consistency = _speaker_consistency(labeled)
    return DiarizationSummary(
        rows=len(rows),
        labeled_rows=len(labeled),
        sessions=len({row.session_id for row in rows}),
        predicted_speakers=len({(row.session_id, row.predicted_speaker) for row in rows}),
        reference_speakers=len({row.reference_speaker for row in labeled}),
        provider_counts=dict(Counter(row.provider or "unknown" for row in rows)),
        merge_state_counts=dict(Counter(row.merge_state or "unknown" for row in rows)),
        mean_confidence=sum(confidences) / len(confidences) if confidences else None,
        speaker_consistency=consistency,
        diarization_error_proxy=(1.0 - consistency) if consistency is not None else None,
        unlabeled_churn_rate=_unlabeled_churn_rate(rows) if not labeled else None,
    )


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Diarization Consistency Benchmark",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Rows | {summary['rows']} |",
        f"| Labeled rows | {summary['labeled_rows']} |",
        f"| Sessions | {summary['sessions']} |",
        f"| Predicted speakers | {summary['predicted_speakers']} |",
        f"| Reference speakers | {summary['reference_speakers']} |",
        f"| Mean confidence | {_format_optional(summary['mean_confidence'])} |",
        f"| Speaker consistency | {_format_optional(summary['speaker_consistency'])} |",
        f"| Diarization error proxy | {_format_optional(summary['diarization_error_proxy'])} |",
        f"| Unlabeled churn rate | {_format_optional(summary['unlabeled_churn_rate'])} |",
        "",
        "## Provider Counts",
        "",
        "| Provider | Rows |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {provider} | {count} |"
        for provider, count in sorted(summary["provider_counts"].items())
    )
    lines.extend(["", "## Merge State Counts", "", "| State | Rows |", "| --- | ---: |"])
    lines.extend(
        f"| {state} | {count} |"
        for state, count in sorted(summary["merge_state_counts"].items())
    )
    lines.extend(
        [
            "",
            "## Per Reference Speaker",
            "",
            "| Reference | Dominant prediction | Consistency | Rows |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    per_reference = payload["per_reference_speaker"]
    if per_reference:
        lines.extend(
            f"| {row['reference_speaker']} | {row['dominant_predicted_speaker']} | "
            f"{_format_optional(row['consistency'])} | {row['rows']} |"
            for row in per_reference
        )
    else:
        lines.append("| none | n/a | n/a | 0 |")
    lines.extend(["", "## Inputs", ""])
    lines.extend(f"- `{path}`" for path in payload["input_files"])
    lines.append("")
    return "\n".join(lines)


def _row_from_record(record: dict[str, Any]) -> DiarizationRow | None:
    utterance = record.get("utterance")
    speaker = record.get("speaker")
    if isinstance(utterance, dict):
        session_id = _string(utterance.get("session_id"))
        utterance_id = _string(utterance.get("utterance_id"))
        predicted_speaker = _string(utterance.get("speaker"))
        text = _string(utterance.get("text"))
        reference = _reference_speaker(record, utterance=utterance)
        confidence = _float_or_none(utterance.get("speaker_confidence"))
        provider = _string_or_none(utterance.get("diarization_provider"))
        merge_state = _string_or_none(utterance.get("speaker_merge_state"))
        if isinstance(speaker, dict):
            confidence = _float_or_none(speaker.get("confidence")) or confidence
            provider = _string_or_none(speaker.get("provider")) or provider
            merge_state = _string_or_none(speaker.get("merge_state")) or merge_state
        if session_id and utterance_id and predicted_speaker:
            return DiarizationRow(
                session_id=session_id,
                utterance_id=utterance_id,
                predicted_speaker=predicted_speaker,
                reference_speaker=reference,
                confidence=confidence,
                provider=provider,
                merge_state=merge_state,
                text=text,
            )

    session_id = _string(record.get("session_id"))
    utterance_id = _string(record.get("utterance_id"))
    predicted_speaker = _string(record.get("speaker") or record.get("predicted_speaker"))
    if session_id and utterance_id and predicted_speaker:
        return DiarizationRow(
            session_id=session_id,
            utterance_id=utterance_id,
            predicted_speaker=predicted_speaker,
            reference_speaker=_reference_speaker(record, utterance={}),
            confidence=_float_or_none(record.get("speaker_confidence") or record.get("confidence")),
            provider=_string_or_none(record.get("diarization_provider") or record.get("provider")),
            merge_state=_string_or_none(
                record.get("speaker_merge_state") or record.get("merge_state")
            ),
            text=_string(record.get("text")),
        )
    return None


def _reference_speaker(record: dict[str, Any], *, utterance: dict[str, Any]) -> str | None:
    for value in (
        record.get("reference_speaker"),
        record.get("expected_speaker"),
        record.get("speaker_label"),
        utterance.get("reference_speaker"),
        utterance.get("expected_speaker"),
        utterance.get("speaker_label"),
    ):
        text = _string_or_none(value)
        if text:
            return text
    speaker = record.get("speaker")
    if isinstance(speaker, dict):
        return _string_or_none(speaker.get("speaker_label"))
    return None


def _speaker_consistency(rows: list[DiarizationRow]) -> float | None:
    if not rows:
        return None
    by_reference: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.reference_speaker is not None:
            by_reference[row.reference_speaker][row.predicted_speaker] += 1
    correct = sum(counter.most_common(1)[0][1] for counter in by_reference.values() if counter)
    total = sum(sum(counter.values()) for counter in by_reference.values())
    return correct / total if total else None


def _unlabeled_churn_rate(rows: list[DiarizationRow]) -> float:
    by_session: dict[str, list[DiarizationRow]] = defaultdict(list)
    for row in rows:
        by_session[row.session_id].append(row)
    transitions = 0
    changes = 0
    for session_rows in by_session.values():
        ordered = sorted(session_rows, key=lambda row: row.utterance_id)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            transitions += 1
            if previous.predicted_speaker != current.predicted_speaker:
                changes += 1
    return changes / transitions if transitions else 0.0


def _per_reference_speaker(rows: list[DiarizationRow]) -> list[dict[str, Any]]:
    by_reference: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.reference_speaker:
            by_reference[row.reference_speaker][row.predicted_speaker] += 1
    output: list[dict[str, Any]] = []
    for reference, counter in sorted(by_reference.items()):
        dominant, count = counter.most_common(1)[0]
        total = sum(counter.values())
        output.append(
            {
                "reference_speaker": reference,
                "dominant_predicted_speaker": dominant,
                "consistency": count / total if total else None,
                "rows": total,
                "predicted_counts": dict(counter),
            }
        )
    return output


def _per_session(rows: list[DiarizationRow]) -> list[dict[str, Any]]:
    by_session: dict[str, list[DiarizationRow]] = defaultdict(list)
    for row in rows:
        by_session[row.session_id].append(row)
    return [
        {
            "session_id": session_id,
            "rows": len(session_rows),
            "predicted_speakers": sorted({row.predicted_speaker for row in session_rows}),
            "reference_speakers": sorted(
                {row.reference_speaker for row in session_rows if row.reference_speaker}
            ),
        }
        for session_id, session_rows in sorted(by_session.items())
    ]


def _string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _string_or_none(value: object) -> str | None:
    text = _string(value)
    return text or None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_optional(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


if __name__ == "__main__":
    main()
