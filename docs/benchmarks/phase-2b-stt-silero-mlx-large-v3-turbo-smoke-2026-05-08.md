# Phase 2B STT Benchmark

Generated: 2026-05-08T18:35:43.653295+00:00

## Summary

| Metric | Value |
| --- | ---: |
| VAD provider | silero_onnx |
| STT provider | mlx_whisper |
| Model | mlx-community/whisper-large-v3-turbo |
| Files | 1 |
| Source audio s | 30.00 |
| Utterance windows | 1 |
| Transcribed speech s | 22.23 |
| Model load s | 20.83 |
| STT wall s | 1.61 |
| RTF | 0.0723 |
| Window wall p50 s | 1.6060 |
| Window wall p95 s | 1.6060 |
| Empty transcript rate | 0.00% |
| Errors | 0 |

## Artifacts

- Artifact dir: `.data/stt/silero-mlx-large-v3-turbo-smoke`
- Windows JSONL: `.data/stt/silero-mlx-large-v3-turbo-smoke/utterance-windows.jsonl`
- Transcripts JSONL: `.data/stt/silero-mlx-large-v3-turbo-smoke/transcripts.jsonl`
- Joined transcript: `.data/stt/silero-mlx-large-v3-turbo-smoke/0a764bab-00c0-41e8-986f-cdfd434b3509_first_30s-transcript.md`

## Model Metadata

- Provider: `mlx_whisper`
- Model ID: `mlx-community/whisper-large-v3-turbo`
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
