# Phase 1 Testing

## Local Backend Smoke Test

```bash
uv run backend
uv run send-test-audio --duration-s 5
curl http://127.0.0.1:8000/api/sessions
```

Expected:

- `send-test-audio` prints `session_ack`, periodic `chunk_ack`, and `session_stopped`.
- Backend logs show audio chunks with non-zero RMS for the synthetic sine wave.
- If `PROOF_AUDIO_DUMP_SECONDS` is greater than `0`, a WAV appears in `.data/audio/`.
- If telemetry is enabled, session JSON and chunk JSONL files appear in `.data/telemetry/`.

## Chrome Extension Build Test

```bash
cd extension
npm run build
```

Expected:

- `extension/dist/manifest.json` exists.
- `extension/dist/assets/background.js`, `offscreen.js`, `pcm-worklet.js`, `popup.js`, `sidepanel.js`, and `content.js` exist.
- Chrome loads `extension/dist` as an unpacked extension without manifest errors.

## Google Meet Live Test

1. Start the backend with `uv run backend`.
2. Build and load the extension from `extension/dist`.
3. Join a Google Meet in Chrome.
4. Click the extension action and press **Start**.
5. Have remote participants speak for 30 to 60 seconds.
6. Watch the popup or side panel.

Expected:

- Capture state becomes `streaming`.
- Backend state becomes `connected`.
- The audio level meter moves with remote participant speech.
- Latency stays below 150 ms for normal local networking.
- Dropped chunk count remains `0`.
- If **Telemetry capture** is enabled in the extension settings, `.data/telemetry/` contains a
  session JSON file and chunk JSONL file for the session.
- The Meet tab still plays remote audio locally because the offscreen document routes captured audio back to the tab audio output.

## Ten-Minute Soak Test

Run a 10+ minute Meet session after the smoke test.

Record the result in `docs/benchmarks/phase-1-audio-capture-YYYY-MM-DD.md` with:

- Chrome version.
- macOS version.
- Meeting size and duration.
- Backend chunk count.
- Dropped chunks.
- Median and p95 chunk latency from UI/backend logs.
- Whether the optional first-30-second WAV is intelligible.
- Any tab navigation, permission, or reconnect issues.
