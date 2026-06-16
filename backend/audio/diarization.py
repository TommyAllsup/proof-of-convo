from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from backend.audio.frames import audio_levels
from backend.audio.stt_windows import UtteranceWindow


@dataclass(frozen=True)
class SpeakerAttribution:
    speaker: str
    confidence: float
    method: str
    provider: str = "heuristic_acoustic"
    merge_state: str = "unknown"
    speaker_label: str | None = None


class DiarizationProvider(Protocol):
    name: str

    def assign(
        self,
        *,
        window: UtteranceWindow,
        audio: NDArray[np.float32],
    ) -> SpeakerAttribution: ...

    def set_speaker_label(self, *, session_id: str, speaker: str, label: str | None) -> None: ...


@dataclass
class _SpeakerCentroid:
    speaker: str
    vector: NDArray[np.float64]
    samples: int = 1


class HeuristicSpeakerDiarizer:
    """Lightweight online speaker attribution until an embedding model is added.

    This is not production diarization. It clusters simple acoustic features so Phase 2 can
    publish stable speaker-attributed utterance events while leaving a clean replacement point for
    Sortformer or speaker embeddings.
    """

    name = "heuristic_acoustic"

    def __init__(self, *, distance_threshold: float = 0.35) -> None:
        self._distance_threshold = distance_threshold
        self._speakers: dict[str, list[_SpeakerCentroid]] = {}
        self._speaker_labels: dict[tuple[str, str], str] = {}

    def assign(
        self,
        *,
        window: UtteranceWindow,
        audio: NDArray[np.float32],
    ) -> SpeakerAttribution:
        vector = _feature_vector(window=window, audio=audio)
        centroids = self._speakers.setdefault(window.session_id, [])
        if not centroids:
            centroid = _SpeakerCentroid(speaker="Speaker_1", vector=vector)
            centroids.append(centroid)
            return self._attribution(
                session_id=window.session_id,
                speaker=centroid.speaker,
                confidence=0.60,
                merge_state="new",
            )

        distances = [float(np.linalg.norm(vector - centroid.vector)) for centroid in centroids]
        best_index = int(np.argmin(np.array(distances)))
        best_distance = distances[best_index]
        if best_distance > self._distance_threshold and len(centroids) < 8:
            speaker = f"Speaker_{len(centroids) + 1}"
            centroids.append(_SpeakerCentroid(speaker=speaker, vector=vector))
            return self._attribution(
                session_id=window.session_id,
                speaker=speaker,
                confidence=0.45,
                merge_state="new",
            )

        centroid = centroids[best_index]
        centroid.samples += 1
        weight = 1.0 / centroid.samples
        centroid.vector = centroid.vector * (1.0 - weight) + vector * weight
        confidence = max(
            0.25,
            min(0.95, 1.0 - best_distance / max(self._distance_threshold, 0.001)),
        )
        return self._attribution(
            session_id=window.session_id,
            speaker=centroid.speaker,
            confidence=confidence,
            merge_state="matched",
        )

    def set_speaker_label(self, *, session_id: str, speaker: str, label: str | None) -> None:
        key = (session_id, speaker)
        cleaned = label.strip() if label else None
        if cleaned:
            self._speaker_labels[key] = cleaned
        else:
            self._speaker_labels.pop(key, None)

    def _attribution(
        self,
        *,
        session_id: str,
        speaker: str,
        confidence: float,
        merge_state: str,
    ) -> SpeakerAttribution:
        return SpeakerAttribution(
            speaker=speaker,
            confidence=confidence,
            method=self.name,
            provider=self.name,
            merge_state=merge_state,
            speaker_label=self._speaker_labels.get((session_id, speaker)),
        )


class SingleSpeakerDiarizer:
    """Deterministic provider for one-speaker local tests and capture smoke runs."""

    name = "single_speaker"

    def __init__(self) -> None:
        self._speaker_labels: dict[tuple[str, str], str] = {}

    def assign(
        self,
        *,
        window: UtteranceWindow,
        audio: NDArray[np.float32],
    ) -> SpeakerAttribution:
        _ = audio
        speaker = "Speaker_1"
        return SpeakerAttribution(
            speaker=speaker,
            confidence=1.0,
            method=self.name,
            provider=self.name,
            merge_state="fixed",
            speaker_label=self._speaker_labels.get((window.session_id, speaker)),
        )

    def set_speaker_label(self, *, session_id: str, speaker: str, label: str | None) -> None:
        key = (session_id, speaker)
        cleaned = label.strip() if label else None
        if cleaned:
            self._speaker_labels[key] = cleaned
        else:
            self._speaker_labels.pop(key, None)


def create_diarization_provider(name: str) -> DiarizationProvider:
    normalized = name.strip().lower()
    if normalized in {"heuristic", "heuristic_acoustic"}:
        return HeuristicSpeakerDiarizer()
    if normalized in {"single", "single_speaker"}:
        return SingleSpeakerDiarizer()
    raise ValueError(
        f"Unsupported diarization provider '{name}'. "
        "Supported providers: heuristic_acoustic, single_speaker."
    )


def _feature_vector(
    *,
    window: UtteranceWindow,
    audio: NDArray[np.float32],
) -> NDArray[np.float64]:
    rms, peak = audio_levels(audio)
    zero_crossing_rate = _zero_crossing_rate(audio)
    duration_s = max(0.0, window.padded_duration_ms / 1000.0)
    return np.array(
        [
            rms * 4.0,
            peak,
            zero_crossing_rate * 10.0,
            min(duration_s / 30.0, 1.0),
        ],
        dtype=np.float64,
    )


def _zero_crossing_rate(audio: NDArray[np.float32]) -> float:
    if audio.size < 2:
        return 0.0
    signs = np.signbit(audio)
    return float(np.count_nonzero(signs[1:] != signs[:-1]) / (audio.size - 1))
