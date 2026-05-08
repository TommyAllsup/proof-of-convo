from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np

from backend.audio.stt_windows import (
    extract_windows_from_wav,
    read_window_pcm16,
    write_windows_jsonl,
)


def test_extract_windows_from_wav_is_deterministic(tmp_path: Path) -> None:
    wav_path = tmp_path / "meeting_first_3600s.wav"
    _write_synthetic_wav(wav_path, pattern=["silence", "silence", "speech", "speech", "speech"])

    first = extract_windows_from_wav(
        wav_path,
        vad_provider="rms",
        chunk_ms=200,
        pre_roll_ms=100,
        post_roll_ms=100,
    )
    second = extract_windows_from_wav(
        wav_path,
        vad_provider="rms",
        chunk_ms=200,
        pre_roll_ms=100,
        post_roll_ms=100,
    )

    assert [window.to_record() for window in first] == [window.to_record() for window in second]
    assert len(first) == 1
    window = first[0]
    assert window.session_id == "meeting_first_3600s"
    assert window.vad_provider == "rms"
    assert window.start_ms == 400
    assert window.end_ms == 1000
    assert window.padded_start_ms == 300
    assert window.padded_end_ms == 1000
    assert window.start_sequence == 2
    assert window.end_sequence == 4
    assert read_window_pcm16(window)


def test_write_windows_jsonl(tmp_path: Path) -> None:
    wav_path = tmp_path / "meeting_first_3600s.wav"
    _write_synthetic_wav(wav_path, pattern=["silence", "speech", "speech"])
    windows = extract_windows_from_wav(wav_path, vad_provider="rms", chunk_ms=200)
    output = tmp_path / "windows.jsonl"

    write_windows_jsonl(windows, output)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["window_id"] == windows[0].window_id
    assert rows[0]["source_wav"] == str(wav_path)


def _write_synthetic_wav(path: Path, *, pattern: list[str]) -> None:
    sample_rate = 16_000
    chunk_ms = 200
    frames_per_chunk = sample_rate * chunk_ms // 1000
    chunks: list[np.ndarray[tuple[int], np.dtype[np.int16]]] = []
    for index, kind in enumerate(pattern):
        if kind == "speech":
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
