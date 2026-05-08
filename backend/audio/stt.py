from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from backend.audio.stt_windows import UtteranceWindow, read_window_float32


@dataclass(frozen=True)
class SttModelInfo:
    provider: str
    model_id: str
    package: str | None = None
    package_version: str | None = None
    quantization: str | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SttTranscript:
    window_id: str
    provider: str
    model_id: str
    text: str
    language: str | None
    confidence: float | None
    wall_time_s: float
    error: str | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class SttProvider(Protocol):
    name: str

    @property
    def model_info(self) -> SttModelInfo: ...

    def prepare(self) -> float | None: ...

    def transcribe(self, window: UtteranceWindow) -> SttTranscript: ...

    def transcribe_audio(
        self,
        window: UtteranceWindow,
        audio: NDArray[np.float32],
    ) -> SttTranscript: ...


class FakeSttProvider:
    name = "fake"

    @property
    def model_info(self) -> SttModelInfo:
        return SttModelInfo(provider=self.name, model_id="fake-deterministic")

    def prepare(self) -> float | None:
        return 0.0

    def transcribe(self, window: UtteranceWindow) -> SttTranscript:
        started = time.perf_counter()
        text = f"[fake transcript {window.window_id} {window.duration_ms:.0f}ms]"
        return SttTranscript(
            window_id=window.window_id,
            provider=self.name,
            model_id=self.model_info.model_id,
            text=text,
            language="en",
            confidence=None,
            wall_time_s=time.perf_counter() - started,
        )

    def transcribe_audio(
        self,
        window: UtteranceWindow,
        audio: NDArray[np.float32],
    ) -> SttTranscript:
        return self.transcribe(window)


class MlxWhisperSttProvider:
    name = "mlx_whisper"

    def __init__(
        self,
        *,
        model_id: str | None = None,
        language: str | None = None,
        word_timestamps: bool = False,
    ) -> None:
        self._model_id = (
            model_id
            if model_id is not None
            else os.getenv("PROOF_STT_MODEL") or "mlx-community/whisper-large-v3-turbo"
        )
        self._language = language
        self._word_timestamps = word_timestamps
        self._package_version = _package_version("mlx-whisper")

    @property
    def model_info(self) -> SttModelInfo:
        return SttModelInfo(
            provider=self.name,
            model_id=self._model_id,
            package="mlx-whisper",
            package_version=self._package_version,
            quantization=None,
        )

    def transcribe(self, window: UtteranceWindow) -> SttTranscript:
        started = time.perf_counter()
        try:
            audio = read_window_float32(window)
        except Exception as exc:  # noqa: BLE001 - benchmark should record provider failures.
            return SttTranscript(
                window_id=window.window_id,
                provider=self.name,
                model_id=self._model_id,
                text="",
                language=None,
                confidence=None,
                wall_time_s=time.perf_counter() - started,
                error=f"{type(exc).__name__}: {exc}",
            )
        return self._transcribe_array(window, audio, started_at=started)

    def transcribe_audio(
        self,
        window: UtteranceWindow,
        audio: NDArray[np.float32],
    ) -> SttTranscript:
        return self._transcribe_array(window, audio, started_at=time.perf_counter())

    def _transcribe_array(
        self,
        window: UtteranceWindow,
        audio: NDArray[np.float32],
        *,
        started_at: float,
    ) -> SttTranscript:
        try:
            import mlx_whisper  # type: ignore[import-untyped]

            result = mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=self._model_id,
                verbose=None,
                language=self._language,
                word_timestamps=self._word_timestamps,
                condition_on_previous_text=False,
            )
            text = str(result.get("text", "")).strip()
            language = result.get("language")
            return SttTranscript(
                window_id=window.window_id,
                provider=self.name,
                model_id=self._model_id,
                text=text,
                language=str(language) if language is not None else None,
                confidence=None,
                wall_time_s=time.perf_counter() - started_at,
            )
        except Exception as exc:  # noqa: BLE001 - benchmark should record provider failures.
            return SttTranscript(
                window_id=window.window_id,
                provider=self.name,
                model_id=self._model_id,
                text="",
                language=None,
                confidence=None,
                wall_time_s=time.perf_counter() - started_at,
                error=f"{type(exc).__name__}: {exc}",
            )

    def prepare(self) -> float | None:
        started = time.perf_counter()
        try:
            import importlib

            import mlx.core as mx

            transcribe_module = importlib.import_module("mlx_whisper.transcribe")
            transcribe_module.ModelHolder.get_model(self._model_id, dtype=mx.float16)
        except Exception:
            return None
        return time.perf_counter() - started


def create_stt_provider(
    name: str,
    *,
    model_id: str | None = None,
    language: str | None = None,
) -> SttProvider:
    if name == "fake":
        return FakeSttProvider()
    if name == "mlx_whisper":
        return MlxWhisperSttProvider(model_id=model_id, language=language)
    raise ValueError(f"unsupported STT provider: {name}")


def _package_version(package_name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:  # noqa: BLE001 - optional metadata only.
        return None
