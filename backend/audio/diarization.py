from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backend.audio.frames import audio_levels
from backend.audio.stt_windows import UtteranceWindow


@dataclass(frozen=True)
class SpeakerAttribution:
    speaker: str
    confidence: float
    method: str


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
            return SpeakerAttribution(speaker=centroid.speaker, confidence=0.60, method=self.name)

        distances = [float(np.linalg.norm(vector - centroid.vector)) for centroid in centroids]
        best_index = int(np.argmin(np.array(distances)))
        best_distance = distances[best_index]
        if best_distance > self._distance_threshold and len(centroids) < 8:
            speaker = f"Speaker_{len(centroids) + 1}"
            centroids.append(_SpeakerCentroid(speaker=speaker, vector=vector))
            return SpeakerAttribution(speaker=speaker, confidence=0.45, method=self.name)

        centroid = centroids[best_index]
        centroid.samples += 1
        weight = 1.0 / centroid.samples
        centroid.vector = centroid.vector * (1.0 - weight) + vector * weight
        confidence = max(
            0.25,
            min(0.95, 1.0 - best_distance / max(self._distance_threshold, 0.001)),
        )
        return SpeakerAttribution(
            speaker=centroid.speaker,
            confidence=confidence,
            method=self.name,
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
