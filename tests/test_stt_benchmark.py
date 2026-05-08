from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np

from scripts.benchmark_stt import run_benchmark


def test_run_benchmark_writes_fake_stt_artifacts(tmp_path: Path) -> None:
    wav_path = tmp_path / "meeting_first_3600s.wav"
    _write_synthetic_wav(wav_path)
    artifact_dir = tmp_path / "artifacts"

    payload = run_benchmark(
        files=[wav_path],
        vad_provider="rms",
        stt_provider_name="fake",
        model_id=None,
        language=None,
        artifact_dir=artifact_dir,
        limit_segments=None,
        max_audio_minutes=None,
        chunk_ms=200,
        pre_roll_ms=100.0,
        post_roll_ms=100.0,
    )

    summary = payload["summary"]
    assert summary["utterance_windows"] == 1
    assert summary["error_count"] == 0
    assert Path(payload["artifacts"]["windows_jsonl"]).exists()
    assert Path(payload["artifacts"]["transcripts_jsonl"]).exists()
    joined = payload["artifacts"]["joined_transcripts"]
    assert len(joined) == 1
    assert Path(joined[0]).exists()

    transcript_rows = [
        json.loads(line)
        for line in Path(payload["artifacts"]["transcripts_jsonl"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert transcript_rows[0]["provider"] == "fake"
    assert transcript_rows[0]["window"]["vad_provider"] == "rms"


def _write_synthetic_wav(path: Path) -> None:
    sample_rate = 16_000
    chunk_ms = 200
    frames_per_chunk = sample_rate * chunk_ms // 1000
    chunks: list[np.ndarray[tuple[int], np.dtype[np.int16]]] = []
    for index, speech in enumerate([False, True, True, False, False, False]):
        if speech:
            samples = np.arange(index * frames_per_chunk, (index + 1) * frames_per_chunk)
            wave_data = 0.35 * np.sin(2.0 * math.pi * 440.0 * samples / sample_rate)
            chunks.append((wave_data * 32767.0).astype("<i2"))
        else:
            chunks.append(np.zeros(frames_per_chunk, dtype="<i2"))

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for chunk in chunks:
            wav.writeframes(chunk.tobytes())
