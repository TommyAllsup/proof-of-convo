from __future__ import annotations

import wave
from pathlib import Path


class WavDumpWriter:
    """Writes the first N seconds of a session to a local WAV for Phase 1 verification."""

    def __init__(self, path: Path, sample_rate: int, max_seconds: int) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.max_samples = sample_rate * max_seconds
        self.samples_written = 0
        self._wav: wave.Wave_write | None = None

    @property
    def enabled(self) -> bool:
        return self.max_samples > 0

    @property
    def complete(self) -> bool:
        return self.samples_written >= self.max_samples

    def write(self, pcm16: bytes) -> None:
        if not self.enabled or self.complete:
            return

        if self._wav is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._wav = wave.open(str(self.path), "wb")  # noqa: SIM115
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self.sample_rate)

        remaining_samples = self.max_samples - self.samples_written
        samples_in_payload = len(pcm16) // 2
        samples_to_write = min(samples_in_payload, remaining_samples)
        if samples_to_write <= 0:
            return

        self._wav.writeframes(pcm16[: samples_to_write * 2])
        self.samples_written += samples_to_write

        if self.complete:
            self.close()

    def close(self) -> None:
        if self._wav is not None:
            self._wav.close()
            self._wav = None
