from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import torch
from silero_vad import load_silero_vad  # type: ignore[import-untyped]

from backend.audio.endpointing import EndpointEvent, RmsEndpointDetector, SpeechSegment
from backend.audio.frames import pcm16_to_float32
from backend.audio.manager import AudioChunkEvent


@dataclass(frozen=True)
class VadFrameStats:
    provider: str
    session_id: str | None
    sequence: int | None
    speech_probability: float | None
    is_speech: bool | None
    rms: float | None
    peak: float | None


class VadProvider(Protocol):
    name: str

    @property
    def latest_frame_stats(self) -> VadFrameStats | None: ...

    def process(self, event: AudioChunkEvent) -> list[EndpointEvent]: ...

    def flush(self, session_id: str) -> SpeechSegment | None: ...


class _SileroModel(Protocol):
    def __call__(self, tensor: torch.Tensor, sampling_rate: int) -> torch.Tensor: ...

    def reset_states(self) -> None: ...


class RmsVadProvider:
    name = "rms"

    def __init__(self, detector: RmsEndpointDetector | None = None) -> None:
        self._detector = detector or RmsEndpointDetector()
        self._latest_frame_stats: VadFrameStats | None = None

    @property
    def latest_frame_stats(self) -> VadFrameStats | None:
        return self._latest_frame_stats

    def process(self, event: AudioChunkEvent) -> list[EndpointEvent]:
        is_speech = event.rms >= self._detector.speech_rms_threshold
        self._latest_frame_stats = VadFrameStats(
            provider=self.name,
            session_id=event.session_id,
            sequence=event.packet.sequence,
            speech_probability=None,
            is_speech=is_speech,
            rms=event.rms,
            peak=event.peak,
        )
        return self._detector.process(event)

    def flush(self, session_id: str) -> SpeechSegment | None:
        return self._detector.flush(session_id)


@dataclass
class _SileroSession:
    model: _SileroModel
    threshold: float
    sampling_rate: int
    min_silence_samples: float
    speech_pad_samples: float
    triggered: bool = False
    temp_end: int = 0
    current_sample: int = 0
    stream_started_at_ms: float | None = None
    open_start_ms: float | None = None
    open_start_sequence: int | None = None
    last_voice_ms: float | None = None
    last_sequence: int | None = None
    peak: float = 0.0
    rms_sum: float = 0.0
    rms_count: int = 0
    pending: np.ndarray | None = None


class SileroOnnxVadProvider:
    name = "silero_onnx"

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 30,
        min_speech_ms: float = 250.0,
    ) -> None:
        self._threshold = threshold
        self._min_silence_duration_ms = min_silence_duration_ms
        self._speech_pad_ms = speech_pad_ms
        self._min_speech_ms = min_speech_ms
        self._sessions: dict[str, _SileroSession] = {}
        self._latest_frame_stats: VadFrameStats | None = None

    @property
    def latest_frame_stats(self) -> VadFrameStats | None:
        return self._latest_frame_stats

    def process(self, event: AudioChunkEvent) -> list[EndpointEvent]:
        if event.packet.sample_rate != 16_000:
            raise ValueError("Silero ONNX VAD requires 16 kHz PCM audio")

        state = self._sessions.get(event.session_id)
        if state is None:
            state = _SileroSession(
                model=load_silero_vad(onnx=True),
                threshold=self._threshold,
                sampling_rate=event.packet.sample_rate,
                min_silence_samples=event.packet.sample_rate * self._min_silence_duration_ms / 1000,
                speech_pad_samples=event.packet.sample_rate * self._speech_pad_ms / 1000,
            )
            self._sessions[event.session_id] = state

        if state.stream_started_at_ms is None:
            state.stream_started_at_ms = event.packet.chunk_started_at_ms

        samples = pcm16_to_float32(event.packet.pcm16)
        pending = state.pending if state.pending is not None else np.array([], dtype=np.float32)
        state.pending = np.concatenate((pending, samples.astype(np.float32, copy=False)))
        emitted: list[EndpointEvent] = []
        probability = 0.0
        while state.pending.size >= 512:
            frame = state.pending[:512]
            state.pending = state.pending[512:]
            tensor = torch.from_numpy(frame)
            result, probability = self._process_tensor(state, tensor)
            if not result:
                continue
            if "start" in result:
                start_ms = _sample_offset_to_ms(state, result["start"])
                state.open_start_ms = start_ms
                state.open_start_sequence = event.packet.sequence
                state.last_voice_ms = event.packet.chunk_started_at_ms + event.packet.duration_ms
                state.last_sequence = event.packet.sequence
                state.peak = event.peak
                state.rms_sum = event.rms
                state.rms_count = 1
                emitted.append(
                    EndpointEvent(
                        type="speech_start",
                        session_id=event.session_id,
                        segment=None,
                        sequence=event.packet.sequence,
                        event_ms=start_ms,
                    )
                )
            elif "end" in result:
                end_ms = _sample_offset_to_ms(state, result["end"])
                segment = self._close(event.session_id, end_ms=end_ms)
                if segment is not None:
                    emitted.append(
                        EndpointEvent(
                            type="speech_end",
                            session_id=event.session_id,
                            segment=segment,
                            sequence=event.packet.sequence,
                            event_ms=end_ms,
                        )
                    )
        is_speech = probability >= self._threshold
        self._latest_frame_stats = VadFrameStats(
            provider=self.name,
            session_id=event.session_id,
            sequence=event.packet.sequence,
            speech_probability=probability,
            is_speech=is_speech,
            rms=event.rms,
            peak=event.peak,
        )

        if (is_speech or emitted) and state.open_start_ms is not None:
            chunk_end_ms = event.packet.chunk_started_at_ms + event.packet.duration_ms
            state.last_voice_ms = chunk_end_ms
            state.last_sequence = event.packet.sequence
            state.peak = max(state.peak, event.peak)
            state.rms_sum += event.rms
            state.rms_count += 1

        return emitted

    def flush(self, session_id: str) -> SpeechSegment | None:
        state = self._sessions.get(session_id)
        if state is None or state.last_voice_ms is None:
            return None
        return self._close(session_id, end_ms=state.last_voice_ms)

    def _close(self, session_id: str, *, end_ms: float) -> SpeechSegment | None:
        state = self._sessions.get(session_id)
        if state is None or state.open_start_ms is None or state.open_start_sequence is None:
            return None

        duration_ms = end_ms - state.open_start_ms
        segment = None
        if duration_ms >= self._min_speech_ms:
            segment = SpeechSegment(
                session_id=session_id,
                start_ms=state.open_start_ms,
                end_ms=end_ms,
                duration_ms=duration_ms,
                start_sequence=state.open_start_sequence,
                end_sequence=state.last_sequence
                if state.last_sequence is not None
                else state.open_start_sequence,
                peak=state.peak,
                mean_rms=state.rms_sum / state.rms_count if state.rms_count else 0.0,
            )

        state.model.reset_states()
        state.open_start_ms = None
        state.open_start_sequence = None
        state.last_voice_ms = None
        state.last_sequence = None
        state.peak = 0.0
        state.rms_sum = 0.0
        state.rms_count = 0
        state.pending = np.array([], dtype=np.float32)
        return segment

    def _process_tensor(
        self, state: _SileroSession, tensor: torch.Tensor
    ) -> tuple[dict[str, int] | None, float]:
        window_size_samples = len(tensor)
        state.current_sample += window_size_samples
        probability = float(state.model(tensor, state.sampling_rate).item())

        if probability >= state.threshold and state.temp_end:
            state.temp_end = 0

        if probability >= state.threshold and not state.triggered:
            state.triggered = True
            speech_start = max(
                0,
                state.current_sample - state.speech_pad_samples - window_size_samples,
            )
            return {"start": int(speech_start)}, probability

        if probability < state.threshold - 0.15 and state.triggered:
            if not state.temp_end:
                state.temp_end = state.current_sample
            if state.current_sample - state.temp_end < state.min_silence_samples:
                return None, probability

            speech_end = state.temp_end + state.speech_pad_samples - window_size_samples
            state.temp_end = 0
            state.triggered = False
            return {"end": int(speech_end)}, probability

        return None, probability


def create_vad_provider(name: str) -> VadProvider:
    normalized = name.strip().lower()
    if normalized == "rms":
        return RmsVadProvider()
    if normalized == "silero_onnx":
        return SileroOnnxVadProvider()
    raise ValueError(f"unsupported VAD provider: {name}")


def _sample_offset_to_ms(state: _SileroSession, sample_offset: int) -> float:
    if state.stream_started_at_ms is None:
        return float(sample_offset) * 1000.0 / state.sampling_rate
    return state.stream_started_at_ms + (float(sample_offset) * 1000.0 / state.sampling_rate)
