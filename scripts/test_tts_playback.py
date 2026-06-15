from __future__ import annotations

import argparse
import os
import time

from backend.config import settings
from backend.tts.playback import create_audio_player
from backend.tts.providers import create_tts_provider


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream a short TTS utterance to null output or a local output device."
    )
    parser.add_argument(
        "--provider",
        choices=["fake", "macos_say", "elevenlabs", "cartesia"],
        default=settings.tts_provider,
    )
    parser.add_argument("--text", default="This is a Proof of Conversation voice routing test.")
    parser.add_argument("--device", default=settings.tts_output_device)
    parser.add_argument("--null", action="store_true", help="Do not open a sounddevice output.")
    parser.add_argument("--voice-id", default=settings.tts_voice_id)
    parser.add_argument("--voice-name", default=settings.tts_voice_name)
    parser.add_argument("--model-id", default=settings.tts_model)
    parser.add_argument("--sample-rate", type=int, default=settings.tts_sample_rate)
    parser.add_argument("--speaking-rate", type=int, default=settings.tts_speaking_rate)
    parser.add_argument("--output-format", default=settings.tts_output_format)
    args = parser.parse_args()

    provider = create_tts_provider(
        args.provider,
        api_key=_api_key(args.provider),
        voice_id=args.voice_id,
        voice_name=args.voice_name,
        model_id=args.model_id,
        base_url=_base_url(args.provider),
        output_format=args.output_format,
        sample_rate=args.sample_rate,
        speaking_rate=args.speaking_rate,
        chunk_size_bytes=settings.tts_chunk_size_bytes,
        cartesia_version=settings.cartesia_version,
    )
    player = create_audio_player(
        playback_enabled=not args.null,
        output_device=args.device,
    )
    info = provider.info
    started = time.perf_counter()
    first_audio_at: float | None = None
    audio_bytes = 0
    chunks = 0
    try:
        for chunk in provider.stream_speech(args.text):
            if not chunk:
                continue
            if first_audio_at is None:
                first_audio_at = time.perf_counter()
            player.write_pcm16(chunk, sample_rate=info.sample_rate)
            audio_bytes += len(chunk)
            chunks += 1
    finally:
        player.close()

    elapsed = time.perf_counter() - started
    ttfa_ms = (first_audio_at - started) * 1000.0 if first_audio_at is not None else None
    ttfa_label = f"{ttfa_ms:.1f}" if ttfa_ms is not None else "n/a"
    print(
        "tts_playback "
        f"provider={info.provider} model={info.model_id} voice={info.voice_name} "
        f"player={player.name} device={player.output_device or 'null'} "
        f"sample_rate={info.sample_rate} chunks={chunks} audio_bytes={audio_bytes} "
        f"ttfa_ms={ttfa_label} "
        f"wall_time_s={elapsed:.3f}"
    )


def _api_key(provider_name: str) -> str | None:
    normalized = provider_name.strip().lower()
    if normalized == "elevenlabs":
        return os.getenv("ELEVENLABS_API_KEY")
    if normalized == "cartesia":
        return os.getenv("CARTESIA_API_KEY")
    return None


def _base_url(provider_name: str) -> str | None:
    normalized = provider_name.strip().lower()
    if normalized == "elevenlabs":
        return settings.elevenlabs_base_url
    if normalized == "cartesia":
        return settings.cartesia_base_url
    return None


if __name__ == "__main__":
    main()
