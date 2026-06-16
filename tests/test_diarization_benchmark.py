from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark_diarization import load_rows, render_markdown, run_benchmark, summarize_rows


def test_diarization_benchmark_scores_labeled_stt_status_json(tmp_path: Path) -> None:
    status_path = tmp_path / "stt-status.json"
    status_path.write_text(
        json.dumps(
            {
                "recent_transcripts": [
                    _stt_item("u1", "Speaker_1", "Avery"),
                    _stt_item("u2", "Speaker_1", "Avery"),
                    _stt_item("u3", "Speaker_2", "Morgan"),
                    _stt_item("u4", "Speaker_1", "Morgan"),
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = run_benchmark(inputs=[status_path])
    summary = payload["summary"]

    assert summary["rows"] == 4
    assert summary["labeled_rows"] == 4
    assert summary["speaker_consistency"] == 0.75
    assert summary["diarization_error_proxy"] == 0.25
    assert summary["provider_counts"] == {"heuristic_acoustic": 4}
    assert payload["per_reference_speaker"][0]["reference_speaker"] == "Avery"

    markdown = render_markdown(payload)
    assert "# Diarization Consistency Benchmark" in markdown
    assert "| Speaker consistency | 0.750 |" in markdown


def test_diarization_benchmark_loads_flat_jsonl_and_reports_unlabeled_churn(
    tmp_path: Path,
) -> None:
    jsonl_path = tmp_path / "rows.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "session_id": "s1",
                        "utterance_id": "001",
                        "speaker": "Speaker_1",
                        "provider": "single_speaker",
                    }
                ),
                json.dumps(
                    {
                        "session_id": "s1",
                        "utterance_id": "002",
                        "speaker": "Speaker_2",
                        "provider": "single_speaker",
                    }
                ),
                json.dumps(
                    {
                        "session_id": "s1",
                        "utterance_id": "003",
                        "speaker": "Speaker_2",
                        "provider": "single_speaker",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = load_rows(jsonl_path)
    summary = summarize_rows(rows)

    assert len(rows) == 3
    assert summary.labeled_rows == 0
    assert summary.speaker_consistency is None
    assert summary.unlabeled_churn_rate == 0.5


def _stt_item(utterance_id: str, speaker: str, label: str) -> dict[str, object]:
    return {
        "completed_at_ms": 1_000.0,
        "utterance": {
            "type": "utterance",
            "utterance_id": utterance_id,
            "session_id": "s1",
            "speaker": speaker,
            "start_ts": 0.0,
            "end_ts": 1.0,
            "start_ms": 0.0,
            "end_ms": 1_000.0,
            "text": f"{label} said something",
            "is_final": True,
            "confidence": 0.9,
            "speaker_confidence": 0.8,
            "speaker_label": label,
            "diarization_provider": "heuristic_acoustic",
            "speaker_merge_state": "matched",
            "stt_provider": "fake",
            "stt_model": "fake",
            "vad_provider": "rms",
            "raw_audio_ref": None,
        },
        "speaker": {
            "speaker": speaker,
            "confidence": 0.8,
            "method": "heuristic_acoustic",
            "provider": "heuristic_acoustic",
            "merge_state": "matched",
            "speaker_label": label,
        },
        "transcript": {
            "window_id": utterance_id,
            "provider": "fake",
            "model_id": "fake",
            "text": f"{label} said something",
            "language": "en",
            "confidence": 0.9,
            "wall_time_s": 0.01,
            "error": None,
        },
    }
