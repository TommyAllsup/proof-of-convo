# Phase 2A STT Benchmark

Generated: 2026-05-08T18:19:56.652808+00:00

## Summary

| Metric | Value |
| --- | ---: |
| VAD provider | silero_onnx |
| STT provider | mlx_whisper |
| Model | mlx-community/whisper-tiny |
| Files | 1 |
| Source audio s | 30.00 |
| Utterance windows | 1 |
| Transcribed speech s | 22.23 |
| Model load s | 0.67 |
| STT wall s | 0.24 |
| RTF | 0.0108 |
| Window wall p50 s | 0.2406 |
| Window wall p95 s | 0.2406 |
| Empty transcript rate | 0.00% |
| Errors | 0 |

## Artifacts

- Artifact dir: `.data/stt/silero-mlx-tiny-smoke`
- Windows JSONL: `.data/stt/silero-mlx-tiny-smoke/utterance-windows.jsonl`
- Transcripts JSONL: `.data/stt/silero-mlx-tiny-smoke/transcripts.jsonl`
- Joined transcript: `.data/stt/silero-mlx-tiny-smoke/0a764bab-00c0-41e8-986f-cdfd434b3509_first_30s-transcript.md`

## Model Metadata

- Provider: `mlx_whisper`
- Model ID: `mlx-community/whisper-tiny`
- Package: `mlx-whisper`
- Package version: `0.4.3`
- Quantization: `None`

## Machine

- Platform: `macOS-26.3.1-arm64-arm-64bit-Mach-O`
- Python: `3.13.12`
- Machine: `arm64`

## Settings

- Chunk ms: `200`
- Pre-roll ms: `150.0`
- Post-roll ms: `250.0`
- Limit segments: `1`
- Max audio minutes: `None`

## Input Files

- `.data/audio/0a764bab-00c0-41e8-986f-cdfd434b3509_first_30s.wav`
