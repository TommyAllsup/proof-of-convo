from __future__ import annotations

import hashlib
import json
import math
import wave
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.audio.endpointing import SpeechSegment
from backend.audio.frames import AudioPacket, audio_levels, pcm16_to_float32
from backend.audio.manager import AudioChunkEvent
from backend.audio.vad import VadProvider, create_vad_provider


@dataclass(frozen=True)
class UtteranceWindow:
    window_id: str
    session_id: str
    source_wav: str
    sample_rate: int
    vad_provider: str
    start_ms: float
    end_ms: float
    duration_ms: float
    padded_start_ms: float
    padded_end_ms: float
    padded_duration_ms: float
    start_sequence: int
    end_sequence: int
    peak: float
    mean_rms: float

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def extract_windows_from_wav(
    path: Path,
    *,
    vad_provider: str | VadProvider = "silero_onnx",
    chunk_ms: int = 200,
    pre_roll_ms: float = 150.0,
    post_roll_ms: float = 250.0,
) -> list[UtteranceWindow]:
    provider = create_vad_provider(vad_provider) if isinstance(vad_provider, str) else vad_provider
    sample_rate, total_frames = wav_metadata(path)
    if sample_rate != 16_000:
        raise ValueError(f"{path} must be 16 kHz mono PCM16 WAV")

    session_id = path.stem
    windows: list[UtteranceWindow] = []
    for event in _iter_wav_events(path, session_id=session_id, chunk_ms=chunk_ms):
        for endpoint_event in provider.process(event):
            if endpoint_event.segment is not None:
                windows.append(
                    _window_from_segment(
                        endpoint_event.segment,
                        path=path,
                        sample_rate=sample_rate,
                        total_frames=total_frames,
                        vad_provider=provider.name,
                        pre_roll_ms=pre_roll_ms,
                        post_roll_ms=post_roll_ms,
                    )
                )

    flushed = provider.flush(session_id)
    if flushed is not None:
        windows.append(
            _window_from_segment(
                flushed,
                path=path,
                sample_rate=sample_rate,
                total_frames=total_frames,
                vad_provider=provider.name,
                pre_roll_ms=pre_roll_ms,
                post_roll_ms=post_roll_ms,
            )
        )

    return windows


def extract_windows(
    paths: Iterable[Path],
    *,
    vad_provider_name: str = "silero_onnx",
    chunk_ms: int = 200,
    pre_roll_ms: float = 150.0,
    post_roll_ms: float = 250.0,
) -> list[UtteranceWindow]:
    windows: list[UtteranceWindow] = []
    for path in paths:
        windows.extend(
            extract_windows_from_wav(
                path,
                vad_provider=vad_provider_name,
                chunk_ms=chunk_ms,
                pre_roll_ms=pre_roll_ms,
                post_roll_ms=post_roll_ms,
            )
        )
    return windows


def wav_metadata(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path} must be mono PCM16 WAV")
        return wav.getframerate(), wav.getnframes()


def read_window_pcm16(window: UtteranceWindow) -> bytes:
    path = Path(window.source_wav)
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != window.sample_rate:
            raise ValueError(f"{path} sample rate changed since window extraction")
        start_frame = _ms_to_frame_floor(window.padded_start_ms, window.sample_rate)
        end_frame = min(
            wav.getnframes(),
            _ms_to_frame_ceil(window.padded_end_ms, window.sample_rate),
        )
        if end_frame <= start_frame:
            return b""
        wav.setpos(start_frame)
        return wav.readframes(end_frame - start_frame)


def read_window_float32(window: UtteranceWindow) -> NDArray[np.float32]:
    return pcm16_to_float32(read_window_pcm16(window))


def write_windows_jsonl(windows: Iterable[UtteranceWindow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for window in windows:
            handle.write(json.dumps(window.to_record(), sort_keys=True) + "\n")


def _iter_wav_events(
    path: Path,
    *,
    session_id: str,
    chunk_ms: int,
) -> Iterable[AudioChunkEvent]:
    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        if sample_rate != 16_000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16 kHz mono PCM16 WAV")
        frames_per_chunk = sample_rate * chunk_ms // 1000
        sequence = 0
        while True:
            pcm16 = wav.readframes(frames_per_chunk)
            if not pcm16:
                return
            sample_count = len(pcm16) // 2
            chunk_started_at_ms = sequence * chunk_ms
            packet = AudioPacket(
                sequence=sequence,
                tab_id=0,
                capture_started_at_ms=0.0,
                chunk_started_at_ms=chunk_started_at_ms,
                client_sent_at_ms=chunk_started_at_ms,
                sample_rate=sample_rate,
                sample_count=sample_count,
                pcm16=pcm16,
            )
            rms, peak = audio_levels(pcm16_to_float32(pcm16))
            yield AudioChunkEvent(
                session_id=session_id,
                packet=packet,
                rms=rms,
                peak=peak,
                received_at_ms=chunk_started_at_ms,
            )
            sequence += 1


def _window_from_segment(
    segment: SpeechSegment,
    *,
    path: Path,
    sample_rate: int,
    total_frames: int,
    vad_provider: str,
    pre_roll_ms: float,
    post_roll_ms: float,
) -> UtteranceWindow:
    file_duration_ms = total_frames / sample_rate * 1000.0
    padded_start_ms = max(0.0, segment.start_ms - pre_roll_ms)
    padded_end_ms = min(file_duration_ms, segment.end_ms + post_roll_ms)
    source_wav = str(path)
    window_id = _window_id(
        source_wav=source_wav,
        session_id=segment.session_id,
        vad_provider=vad_provider,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
    )
    return UtteranceWindow(
        window_id=window_id,
        session_id=segment.session_id,
        source_wav=source_wav,
        sample_rate=sample_rate,
        vad_provider=vad_provider,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        duration_ms=max(0.0, segment.end_ms - segment.start_ms),
        padded_start_ms=padded_start_ms,
        padded_end_ms=padded_end_ms,
        padded_duration_ms=max(0.0, padded_end_ms - padded_start_ms),
        start_sequence=segment.start_sequence,
        end_sequence=segment.end_sequence,
        peak=segment.peak,
        mean_rms=segment.mean_rms,
    )


def _window_id(
    *,
    source_wav: str,
    session_id: str,
    vad_provider: str,
    start_ms: float,
    end_ms: float,
) -> str:
    material = f"{source_wav}|{session_id}|{vad_provider}|{start_ms:.3f}|{end_ms:.3f}"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _ms_to_frame_floor(value_ms: float, sample_rate: int) -> int:
    return max(0, int(math.floor(value_ms * sample_rate / 1000.0)))


def _ms_to_frame_ceil(value_ms: float, sample_rate: int) -> int:
    return max(0, int(math.ceil(value_ms * sample_rate / 1000.0)))
