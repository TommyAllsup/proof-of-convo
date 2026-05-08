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
    vad_provider: str = os.getenv("PROOF_VAD_PROVIDER", "rms")
    stt_enabled: bool = _env_bool("PROOF_STT_ENABLED", False)
    stt_provider: str = os.getenv("PROOF_STT_PROVIDER", "fake")
    stt_model: str | None = os.getenv("PROOF_STT_MODEL")
    stt_language: str | None = os.getenv("PROOF_STT_LANGUAGE")
    stt_queue_max: int = _env_int("PROOF_STT_QUEUE_MAX", 32)
    stt_buffer_history_ms: float = _env_float("PROOF_STT_BUFFER_HISTORY_MS", 120_000.0)
    stt_pre_roll_ms: float = _env_float("PROOF_STT_PRE_ROLL_MS", 150.0)
    stt_post_roll_ms: float = _env_float("PROOF_STT_POST_ROLL_MS", 250.0)


settings = Settings()
