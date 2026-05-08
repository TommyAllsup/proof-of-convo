# Phase 2A STT Benchmark

Generated: 2026-05-08T18:21:02.420899+00:00

## Summary

| Metric | Value |
| --- | ---: |
| VAD provider | silero_onnx |
| STT provider | mlx_whisper |
| Model | mlx-community/whisper-tiny |
| Files | 8 |
| Source audio s | 3879.20 |
| Utterance windows | 344 |
| Transcribed speech s | 2719.80 |
| Model load s | 0.69 |
| STT wall s | 34.09 |
| RTF | 0.0125 |
| Window wall p50 s | 0.0439 |
| Window wall p95 s | 0.4237 |
| Empty transcript rate | 11.63% |
| Errors | 0 |

## Artifacts

- Artifact dir: `.data/stt/silero-mlx-tiny-full`
- Windows JSONL: `.data/stt/silero-mlx-tiny-full/utterance-windows.jsonl`
- Transcripts JSONL: `.data/stt/silero-mlx-tiny-full/transcripts.jsonl`
- Joined transcript: `.data/stt/silero-mlx-tiny-full/28b11907-34cb-4a7b-a1b9-35e5732ffd1e_first_3600s-transcript.md`
- Joined transcript: `.data/stt/silero-mlx-tiny-full/2fab3853-9d9d-4acb-8294-44785f42a2d2_first_3600s-transcript.md`
- Joined transcript: `.data/stt/silero-mlx-tiny-full/6e00fa5f-180b-4545-907d-eb6aef73a1c0_first_3600s-transcript.md`
- Joined transcript: `.data/stt/silero-mlx-tiny-full/f819e6b7-4a7c-4719-bc3b-0bbc53dd4b69_first_3600s-transcript.md`

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
- Limit segments: `None`
- Max audio minutes: `None`

## Input Files

- `.data/audio/28b11907-34cb-4a7b-a1b9-35e5732ffd1e_first_3600s.wav`
- `.data/audio/2fab3853-9d9d-4acb-8294-44785f42a2d2_first_3600s.wav`
- `.data/audio/61f874fe-d881-4223-8446-58db40f7b861_first_3600s.wav`
- `.data/audio/6e00fa5f-180b-4545-907d-eb6aef73a1c0_first_3600s.wav`
- `.data/audio/f819e6b7-4a7c-4719-bc3b-0bbc53dd4b69_first_3600s.wav`
- `.data/audio/test-4046ab07-ac72-457c-bc88-45b276af297b_first_3600s.wav`
- `.data/audio/test-ac2c7c59-3ccc-4f70-aff3-d0fbace73d81_first_3600s.wav`
- `.data/audio/test-af873b69-38cc-43dd-aeae-6379f5452b88_first_3600s.wav`
