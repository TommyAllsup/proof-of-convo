# ADR 006: Phase 2C Speaker-Attributed Transcript Publishing

Date: 2026-05-08

## Status

Accepted.

## Context

Phase 2B made live STT possible without blocking the audio queue-drain loop. The remaining Phase 2
work was to turn raw STT results into structured, speaker-attributed utterance events and make them
visible in the extension UI.

True online diarization with embeddings or Sortformer remains a dedicated model-integration task.
For the POC, the immediate need is a stable transcript event surface and a replaceable speaker
attribution seam.

## Decision

Publish final STT results as `Utterance` records with:

- timing,
- transcript text,
- STT provider/model metadata,
- VAD provider metadata,
- `Speaker_N` attribution,
- speaker confidence,
- raw audio reference.

Use a lightweight `HeuristicSpeakerDiarizer` for now. It clusters simple acoustic features per
session and returns stable `Speaker_N` labels. This is explicitly not production diarization, but it
lets downstream UI and agent brain work against the correct event shape while preserving a clean
replacement point for a real diarization model.

## Implementation

- `backend/models/audio.py` defines the `Utterance` Pydantic schema.
- `backend/audio/diarization.py` defines `HeuristicSpeakerDiarizer` and `SpeakerAttribution`.
- `backend/audio/live_stt.py` now converts completed STT jobs into speaker-attributed `Utterance`
  records and stores them in recent transcript history.
- `/api/stt` returns worker stats plus recent transcript items containing `utterance`, `speaker`,
  raw STT result, and window metadata.
- The extension adds `useSttStatus`, STT/utterance TypeScript types, and a Transcript card in the
  popup/sidebar.

## Verification

- `uv run ruff check .`
- `uv run mypy .`
- `uv run pytest` passed with 23 tests.
- `cd extension && npm run typecheck`
- `cd extension && npm run lint`
- `cd extension && npm run build`
- Full-stack WebSocket smoke on port 8022 with fake STT produced one `/api/stt` recent transcript
  with `utterance.type=utterance`, `speaker=Speaker_1`, `stt_provider=fake`, and zero processing
  errors.
- Production-provider WebSocket replay smoke on port 8024 produced one `/api/stt` recent transcript
  with `utterance.type=utterance`, `speaker=Speaker_1`,
  `stt_provider=mlx_whisper`, `stt_model=mlx-community/whisper-large-v3-turbo`, non-empty text, and
  zero processing errors.

## Consequences

- The extension can now show live final transcripts once STT is enabled.
- The agent brain can consume a stable `Utterance` schema in the next phase.
- Speaker labels are approximate until a real diarization provider replaces the heuristic adapter.
