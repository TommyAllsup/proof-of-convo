from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("PROOF_BACKEND_HOST", "127.0.0.1")
    port: int = _env_int("PROOF_BACKEND_PORT", 8000)
    reload: bool = _env_bool("PROOF_BACKEND_RELOAD", False)
    log_level: str = os.getenv("PROOF_LOG_LEVEL", "INFO")
    audio_dump_dir: Path = Path(os.getenv("PROOF_AUDIO_DUMP_DIR", ".data/audio"))
    audio_dump_seconds: int = _env_int("PROOF_AUDIO_DUMP_SECONDS", 30)
    audio_queue_max: int = _env_int("PROOF_AUDIO_QUEUE_MAX", 512)


settings = Settings()
