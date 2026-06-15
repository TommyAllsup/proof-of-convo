from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AudioOutputDevice:
    index: int
    name: str
    max_output_channels: int
    default_samplerate: float


class AudioPlayer(Protocol):
    name: str
    output_device: str | None

    def write_pcm16(self, pcm16: bytes, *, sample_rate: int) -> None: ...

    def close(self) -> None: ...


class NullAudioPlayer:
    name = "null"
    output_device: str | None = None

    def __init__(self) -> None:
        self.total_bytes = 0

    def write_pcm16(self, pcm16: bytes, *, sample_rate: int) -> None:
        _ = sample_rate
        self.total_bytes += len(pcm16)

    def close(self) -> None:
        return


class SoundDeviceAudioPlayer:
    name = "sounddevice"

    def __init__(self, *, output_device: str | None = None, channels: int = 1) -> None:
        self.output_device = output_device
        self._channels = channels
        self._stream: Any | None = None
        self._stream_sample_rate: int | None = None

    def write_pcm16(self, pcm16: bytes, *, sample_rate: int) -> None:
        stream = self._ensure_stream(sample_rate)
        stream.write(pcm16)

    def close(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._stream_sample_rate = None

    def _ensure_stream(self, sample_rate: int) -> Any:
        if self._stream is not None and self._stream_sample_rate == sample_rate:
            return self._stream

        self.close()
        import sounddevice as sd

        device = resolve_output_device(self.output_device)
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate,
            blocksize=0,
            device=device,
            channels=self._channels,
            dtype="int16",
        )
        self._stream.start()
        self._stream_sample_rate = sample_rate
        return self._stream


def create_audio_player(*, playback_enabled: bool, output_device: str | None) -> AudioPlayer:
    if not playback_enabled:
        return NullAudioPlayer()
    return SoundDeviceAudioPlayer(output_device=output_device)


def resolve_output_device(device: str | None) -> int | None:
    if device is None or not device.strip():
        return None
    value = device.strip()
    if value.isdigit():
        return int(value)

    import sounddevice as sd

    devices = sd.query_devices()
    matches: list[int] = []
    for index, item in enumerate(devices):
        name = str(item.get("name", ""))
        max_outputs = int(item.get("max_output_channels", 0))
        if max_outputs > 0 and value.lower() in name.lower():
            matches.append(index)
    if not matches:
        raise RuntimeError(f"output audio device not found: {device}")
    return matches[0]


def list_output_devices() -> list[AudioOutputDevice]:
    import sounddevice as sd

    devices = sd.query_devices()
    output_devices: list[AudioOutputDevice] = []
    for index, item in enumerate(devices):
        max_outputs = int(item.get("max_output_channels", 0))
        if max_outputs <= 0:
            continue
        output_devices.append(
            AudioOutputDevice(
                index=index,
                name=str(item.get("name", "")),
                max_output_channels=max_outputs,
                default_samplerate=float(item.get("default_samplerate", 0.0)),
            )
        )
    return output_devices

