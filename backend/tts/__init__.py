"""Phase 3 text-to-speech providers, playback, and orchestration."""
from backend.tts.orchestrator import TtsOrchestrator, TtsSpeechResult, TtsStats
from backend.tts.playback import create_audio_player
from backend.tts.providers import create_tts_provider

__all__ = [
    "TtsOrchestrator",
    "TtsSpeechResult",
    "TtsStats",
    "create_audio_player",
    "create_tts_provider",
]
