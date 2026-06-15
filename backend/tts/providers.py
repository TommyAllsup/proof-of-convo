from __future__ import annotations

import base64
import json
import math
import urllib.parse
import urllib.request
import uuid
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TtsProviderInfo:
    provider: str
    model_id: str
    voice_id: str
    voice_name: str
    sample_rate: int
    encoding: str


class TtsProvider(Protocol):
    @property
    def info(self) -> TtsProviderInfo: ...

    def stream_speech(self, text: str) -> Iterator[bytes]: ...


class FakeTtsProvider:
    def __init__(
        self,
        *,
        voice_name: str = "meeting-agent",
        sample_rate: int = 24_000,
        chunk_ms: int = 50,
    ) -> None:
        self._info = TtsProviderInfo(
            provider="fake",
            model_id="fake-sine",
            voice_id="fake",
            voice_name=voice_name,
            sample_rate=sample_rate,
            encoding="pcm_s16le",
        )
        self._chunk_samples = max(1, int(sample_rate * chunk_ms / 1000))

    @property
    def info(self) -> TtsProviderInfo:
        return self._info

    def stream_speech(self, text: str) -> Iterator[bytes]:
        duration_s = min(4.0, max(0.25, len(text) / 80.0))
        total_samples = int(self.info.sample_rate * duration_s)
        produced = 0
        while produced < total_samples:
            sample_count = min(self._chunk_samples, total_samples - produced)
            samples = array("h")
            for index in range(sample_count):
                position = produced + index
                envelope = min(1.0, position / 400.0, (total_samples - position) / 400.0)
                radians = 2.0 * math.pi * 440.0 * position / self.info.sample_rate
                value = int(2400 * envelope * math.sin(radians))
                samples.append(value)
            yield samples.tobytes()
            produced += sample_count


class ElevenLabsTtsProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        voice_id: str | None,
        voice_name: str,
        model_id: str | None,
        base_url: str,
        output_format: str,
        sample_rate: int,
        chunk_size_bytes: int,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._output_format = output_format
        self._chunk_size_bytes = chunk_size_bytes
        resolved_model = model_id or "eleven_flash_v2_5"
        resolved_voice_id = voice_id or ""
        self._info = TtsProviderInfo(
            provider="elevenlabs",
            model_id=resolved_model,
            voice_id=resolved_voice_id,
            voice_name=voice_name,
            sample_rate=sample_rate,
            encoding="pcm_s16le",
        )

    @property
    def info(self) -> TtsProviderInfo:
        return self._info

    def stream_speech(self, text: str) -> Iterator[bytes]:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is required for PROOF_TTS_PROVIDER=elevenlabs")
        if not self.info.voice_id:
            raise RuntimeError("PROOF_TTS_VOICE_ID is required for PROOF_TTS_PROVIDER=elevenlabs")

        query = urllib.parse.urlencode({"output_format": self._output_format})
        url = f"{self._base_url}/v1/text-to-speech/{self.info.voice_id}/stream?{query}"
        body = {
            "text": text,
            "model_id": self.info.model_id,
            "voice_settings": {
                "stability": 0.48,
                "similarity_boost": 0.75,
                "style": 0.18,
                "use_speaker_boost": True,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "xi-api-key": self._api_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            while True:
                chunk = response.read(self._chunk_size_bytes)
                if not chunk:
                    break
                yield chunk


class CartesiaTtsProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        voice_id: str | None,
        voice_name: str,
        model_id: str | None,
        base_url: str,
        version: str,
        sample_rate: int,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._version = version
        resolved_model = model_id or "sonic-3"
        resolved_voice_id = voice_id or ""
        self._info = TtsProviderInfo(
            provider="cartesia",
            model_id=resolved_model,
            voice_id=resolved_voice_id,
            voice_name=voice_name,
            sample_rate=sample_rate,
            encoding="pcm_s16le",
        )

    @property
    def info(self) -> TtsProviderInfo:
        return self._info

    def stream_speech(self, text: str) -> Iterator[bytes]:
        if not self._api_key:
            raise RuntimeError("CARTESIA_API_KEY is required for PROOF_TTS_PROVIDER=cartesia")
        if not self.info.voice_id:
            raise RuntimeError("PROOF_TTS_VOICE_ID is required for PROOF_TTS_PROVIDER=cartesia")

        from websockets.sync.client import connect

        query = urllib.parse.urlencode({"cartesia_version": self._version})
        url = f"{self._base_url}?{query}"
        request: dict[str, Any] = {
            "model_id": self.info.model_id,
            "transcript": text,
            "voice": {"mode": "id", "id": self.info.voice_id},
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": self.info.sample_rate,
            },
            "language": "en",
            "context_id": uuid.uuid4().hex,
        }
        with connect(url, additional_headers={"X-API-Key": self._api_key}) as websocket:
            websocket.send(json.dumps(request))
            while True:
                message = websocket.recv()
                payload = json.loads(message) if isinstance(message, str) else message
                if isinstance(payload, bytes):
                    yield payload
                    continue
                if payload.get("type") in {"done", "generation_done"} or payload.get("done"):
                    break
                if payload.get("type") in {"error", "generation_error"}:
                    raise RuntimeError(str(payload))
                data = payload.get("data") or payload.get("audio")
                if isinstance(data, str):
                    yield base64.b64decode(data)


def create_tts_provider(
    provider_name: str,
    *,
    api_key: str | None,
    voice_id: str | None,
    voice_name: str,
    model_id: str | None,
    base_url: str | None,
    output_format: str,
    sample_rate: int,
    chunk_size_bytes: int,
    cartesia_version: str,
) -> TtsProvider:
    normalized = provider_name.strip().lower()
    if normalized == "fake":
        return FakeTtsProvider(voice_name=voice_name, sample_rate=sample_rate)
    if normalized == "elevenlabs":
        return ElevenLabsTtsProvider(
            api_key=api_key,
            voice_id=voice_id,
            voice_name=voice_name,
            model_id=model_id,
            base_url=base_url or "https://api.elevenlabs.io",
            output_format=output_format,
            sample_rate=sample_rate,
            chunk_size_bytes=chunk_size_bytes,
        )
    if normalized == "cartesia":
        return CartesiaTtsProvider(
            api_key=api_key,
            voice_id=voice_id,
            voice_name=voice_name,
            model_id=model_id,
            base_url=base_url or "wss://api.cartesia.ai/tts/websocket",
            version=cartesia_version,
            sample_rate=sample_rate,
        )
    raise ValueError(f"unsupported TTS provider: {provider_name}")
