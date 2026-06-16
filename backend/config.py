from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("PROOF_BACKEND_HOST", "127.0.0.1")
    port: int = _env_int("PROOF_BACKEND_PORT", 8000)
    reload: bool = _env_bool("PROOF_BACKEND_RELOAD", False)
    log_level: str = os.getenv("PROOF_LOG_LEVEL", "INFO")
    audio_dump_dir: Path = Path(os.getenv("PROOF_AUDIO_DUMP_DIR", ".data/audio"))
    audio_dump_seconds: int = _env_int("PROOF_AUDIO_DUMP_SECONDS", 30)
    audio_queue_max: int = _env_int("PROOF_AUDIO_QUEUE_MAX", 512)
    telemetry_enabled: bool = _env_bool("PROOF_TELEMETRY_ENABLED", True)
    telemetry_dir: Path = Path(os.getenv("PROOF_TELEMETRY_DIR", ".data/telemetry"))
    agent_summary_dir: Path = Path(os.getenv("PROOF_AGENT_SUMMARY_DIR", ".data/agent"))
    agent_llm_provider: str = os.getenv("PROOF_AGENT_LLM_PROVIDER", "none")
    agent_llm_model: str = os.getenv("PROOF_AGENT_LLM_MODEL", "gpt-5.5")
    agent_llm_base_url: str = os.getenv("PROOF_AGENT_LLM_BASE_URL", "https://api.openai.com/v1")
    agent_llm_timeout_s: float = _env_float("PROOF_AGENT_LLM_TIMEOUT_S", 2.0)
    agent_llm_max_output_tokens: int = _env_int("PROOF_AGENT_LLM_MAX_OUTPUT_TOKENS", 220)
    agent_llm_reasoning_prompt_suffix: str | None = (
        os.getenv("PROOF_AGENT_LLM_REASONING_PROMPT_SUFFIX") or None
    )
    agent_llm_direct_answer_prompt_suffix: str | None = (
        os.getenv("PROOF_AGENT_LLM_DIRECT_ANSWER_PROMPT_SUFFIX") or None
    )
    agent_llm_context_summary_prompt_suffix: str | None = (
        os.getenv("PROOF_AGENT_LLM_CONTEXT_SUMMARY_PROMPT_SUFFIX") or None
    )
    vad_provider: str = os.getenv("PROOF_VAD_PROVIDER", "rms")
    diarization_provider: str = os.getenv("PROOF_DIARIZATION_PROVIDER", "heuristic_acoustic")
    stt_enabled: bool = _env_bool("PROOF_STT_ENABLED", False)
    stt_provider: str = os.getenv("PROOF_STT_PROVIDER", "fake")
    stt_model: str | None = os.getenv("PROOF_STT_MODEL")
    stt_language: str | None = os.getenv("PROOF_STT_LANGUAGE")
    stt_queue_max: int = _env_int("PROOF_STT_QUEUE_MAX", 32)
    stt_buffer_history_ms: float = _env_float("PROOF_STT_BUFFER_HISTORY_MS", 120_000.0)
    stt_pre_roll_ms: float = _env_float("PROOF_STT_PRE_ROLL_MS", 150.0)
    stt_post_roll_ms: float = _env_float("PROOF_STT_POST_ROLL_MS", 250.0)
    tts_enabled: bool = _env_bool("PROOF_TTS_ENABLED", False)
    tts_provider: str = os.getenv("PROOF_TTS_PROVIDER", "fake")
    tts_model: str | None = os.getenv("PROOF_TTS_MODEL")
    tts_voice_id: str | None = os.getenv("PROOF_TTS_VOICE_ID")
    tts_voice_name: str = os.getenv("PROOF_TTS_VOICE_NAME", "meeting-agent")
    tts_output_format: str = os.getenv("PROOF_TTS_OUTPUT_FORMAT", "pcm_24000")
    tts_sample_rate: int = _env_int("PROOF_TTS_SAMPLE_RATE", 24_000)
    tts_speaking_rate: int = _env_int("PROOF_TTS_SPEAKING_RATE", 165)
    tts_queue_max: int = _env_int("PROOF_TTS_QUEUE_MAX", 4)
    tts_output_device: str | None = os.getenv("PROOF_TTS_OUTPUT_DEVICE", "BlackHole")
    tts_playback_enabled: bool = _env_bool("PROOF_TTS_PLAYBACK_ENABLED", False)
    tts_chunk_size_bytes: int = _env_int("PROOF_TTS_CHUNK_SIZE_BYTES", 4096)
    tts_dump_dir: Path = Path(os.getenv("PROOF_TTS_DUMP_DIR", ".data/tts"))
    tts_dump_enabled: bool = _env_bool("PROOF_TTS_DUMP_ENABLED", False)
    elevenlabs_api_key: str | None = os.getenv("ELEVENLABS_API_KEY") or None
    elevenlabs_base_url: str = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")
    cartesia_api_key: str | None = os.getenv("CARTESIA_API_KEY") or None
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    cartesia_base_url: str = os.getenv(
        "CARTESIA_WS_URL",
        "wss://api.cartesia.ai/tts/websocket",
    )
    cartesia_version: str = os.getenv("CARTESIA_VERSION", "2025-04-16")


settings = Settings()
