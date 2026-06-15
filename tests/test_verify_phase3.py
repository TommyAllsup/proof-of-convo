from __future__ import annotations

from backend.tts.playback import AudioOutputDevice
from scripts.verify_phase3 import find_output_device


def test_find_output_device_by_index() -> None:
    devices = [
        AudioOutputDevice(
            index=3,
            name="BlackHole 2ch",
            max_output_channels=2,
            default_samplerate=48000.0,
        )
    ]

    assert find_output_device(devices, "3") == devices[0]


def test_find_output_device_by_name() -> None:
    devices = [
        AudioOutputDevice(
            index=7,
            name="BlackHole 2ch",
            max_output_channels=2,
            default_samplerate=48000.0,
        )
    ]

    assert find_output_device(devices, "blackhole") == devices[0]


def test_find_output_device_missing() -> None:
    devices = [
        AudioOutputDevice(
            index=1,
            name="MacBook Pro Speakers",
            max_output_channels=2,
            default_samplerate=48000.0,
        )
    ]

    assert find_output_device(devices, "BlackHole") is None
