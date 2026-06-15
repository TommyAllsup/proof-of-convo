from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TtsSpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    interrupt: bool = False


class TtsSpeakResponse(BaseModel):
    type: Literal["tts_speak_queued"] = "tts_speak_queued"
    job_id: str
    queued_at_ms: float
    text: str


class TtsInterruptResponse(BaseModel):
    type: Literal["tts_interrupted"] = "tts_interrupted"
    interrupted: bool
    reason: str
    received_at_ms: float
