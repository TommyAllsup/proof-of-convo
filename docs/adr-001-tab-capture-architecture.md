# ADR 001: MV3 Tab Audio Capture Architecture

Date: 2026-05-05

## Status

Accepted for Phase 1.

## Context

Phase 1 needs reliable Google Meet tab audio capture in a Manifest V3 Chrome extension and long-running audio processing with Web Audio. Chrome extension service workers cannot use DOM/Web Audio APIs directly, and tab capture requires a user-invoked extension flow.

Chrome's current extension documentation says `chrome.tabCapture` can access a tab `MediaStream` only after the user invokes the extension. It also documents that, starting in Chrome 116, a stream ID obtained in a service worker can be consumed by an offscreen document with the same extension origin. The offscreen API exists for DOM-only work that service workers cannot perform, and only exposes limited extension APIs, so runtime messaging must bridge control state.

Primary references:

- Chrome `tabCapture` API reference: https://developer.chrome.com/docs/extensions/reference/api/tabCapture
- Chrome offscreen API reference: https://developer.chrome.com/docs/extensions/reference/api/offscreen
- Chrome audio recording and screen capture guide: https://developer.chrome.com/docs/extensions/how-to/web-platform/screen-capture
- Chrome 116 extension updates: https://developer.chrome.com/blog/chrome-116-beta-whats-new-for-extensions

## Decision

Use this Phase 1 architecture:

1. Popup or side-panel button is the user gesture.
2. The extension UI queries the active Meet tab and calls `chrome.tabCapture.getMediaStreamId({ targetTabId })`.
3. The service worker creates or reuses `offscreen.html`.
4. The service worker sends the one-use stream ID to the offscreen document.
5. The offscreen document calls `navigator.mediaDevices.getUserMedia()` with `chromeMediaSource: "tab"` and the stream ID.
6. Web Audio preserves local tab playback by routing the captured stream to `AudioContext.destination`.
7. An `AudioWorklet` downsamples to 16 kHz mono PCM16 and emits 200 ms chunks.
8. The offscreen document streams a JSON `session_start`, binary PCM packets, and `session_stop` to the local backend WebSocket.
9. The backend returns throttled chunk acknowledgements with latency, RMS, peak, and dropped-chunk counters for the UI.

## Consequences

- Requires Chrome 116+.
- One active capture session is supported in Phase 1. Multiple Meet tabs are handled by explicit active-tab selection; starting another tab replaces the current session.
- The service worker remains a coordinator rather than an audio processor.
- If the backend disconnects, the offscreen document buffers a bounded number of chunks and reconnects with exponential backoff.
- `tabCapture` captures remote tab output only, not the local microphone, which is the desired Phase 1 behavior.

## Follow-Ups

- Add a real Google Meet soak-test result under `docs/benchmarks/` after manual testing with multiple participants.
- Revisit a native macOS audio capture companion only if tab capture proves unstable during 10+ minute meetings.

