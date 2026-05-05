# AGENTS.md

**Proof of Conversation: Building a Live Agentic Participant for Online Meetings**

This document provides a comprehensive, prescriptive guide for AI coding agents, researchers, and developers working on this repository. It expands the initial project notes into a detailed, phased implementation roadmap with specific, actionable steps, decision criteria, benchmarks, pitfalls to avoid, and success metrics. The goal is to enable autonomous or semi-autonomous progress toward a working proof-of-concept (POC).

Follow this document sequentially or by assigned phase/subtask. Always update this file with Architecture Decision Records (ADRs), benchmark results, and lessons learned after completing major steps. Use clear commit messages referencing phases (e.g., `feat: phase-2-stt-pipeline-vad-implementation`).

---

## 1. Project Goal

Build a **live, agentic AI participant** that can join and meaningfully contribute to online meetings (initially Google Meet via Google Chrome). The agent must:

- Listen in real-time with low latency.
- Transcribe audio with **speaker identification** (diarization).
- Maintain conversation context and understanding.
- Proactively or reactively participate by **asking questions**, providing insights, summarizing, or driving discussion in a natural way.
- Generate and deliver **super-realistic voice output** that sounds like a human colleague.
- Switch seamlessly between passive listening and active interactive modes.

**Initial POC Constraints & Enablers**:
- Platform: Google Meet in Google Chrome (desktop).
- Allow Chrome extensions/plugins.
- Local compute: Dedicated Apple M4 Mac with 64 GB unified RAM (excellent for MLX-accelerated inference).
- Hybrid cloud/local acceptable for speed-to-POC, but prioritize local processing for latency, privacy, and cost where feasible.
- Focus on **natural turn-taking**, low end-to-end latency (< ~1.5–2.5 seconds from end-of-human-utterance to start of agent speech for natural feel), and helpful but non-intrusive behavior.

**Success for POC**: A working end-to-end loop in a real (or simulated) multi-speaker Google Meet where the agent transcribes accurately, understands context, decides to speak at appropriate moments, and delivers realistic voice that other participants can hear clearly, with measurable low latency and positive qualitative feedback on naturalness.

---

## 2. Key Technical Challenges & High-Level Vision

### Core Hard Problems
1. **Low-latency, high-accuracy audio ingestion + STT + diarization** in a streaming, multi-speaker environment (overlapping speech, varying accents, background noise, WebRTC audio artifacts from Meet).
2. **Natural conversational intelligence**: Detecting end-of-turn (not just silence, but prosody/completeness), maintaining long-context meeting state (topics, decisions, open questions, participant goals), deciding *when* and *what* to say without being annoying or interrupting.
3. **Super-realistic, low-latency voice synthesis + injection** into the meeting audio stream so the agent is heard as a legitimate participant.
4. **Seamless Chrome/Meet integration** without breaking the meeting UX or requiring users to switch tools.
5. **Robust real-time state management** and graceful degradation (e.g., when diarization is uncertain or LLM is slow).

### High-Level Architecture Vision (Text + Mermaid)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Google Meet (Chrome Tab)                           │
│  ┌──────────────────────┐          ┌──────────────────────────────┐         │
│  │   Remote Participants│          │   Chrome Extension (UI)      │         │
│  │   Audio (WebRTC)     │─────────▶│   - Live transcript sidebar  │         │
│  └──────────────────────┘  tabCapture│   - Agent status / thoughts│         │
│                                      │   - Mode controls (passive/│         │
│                                      │     active / Q&A)          │         │
│                                      │   - Manual speak trigger   │         │
└──────────────────────────────────────┼──────────────────────────────┘
                                       │ WebSocket (binary audio + JSON events)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Local Backend (Python on M4 Mac)                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │   Audio      │──▶│   VAD +      │──▶│   Streaming  │──▶│   Structured │  │
│  │   Ingestion  │   │   Chunking   │   │   STT +      │   │   Utterance  │  │
│  │   (WS)       │   │   (Silero)   │   │   Diarization│   │   Events     │  │
│  └──────────────┘   └──────────────┘   │   (MLX Whisper│   └──────┬───────┘  │
│                                        │    Turbo +    │          │          │
│                                        │    Sortformer)│          │          │
│                                        └──────────────┘          │          │
│                                                                  │          │
│  ┌───────────────────────────────────────────────────────────────┘          │
│  │                    Conversation Context & Agent Brain                     │
│  │  - Rolling transcript + hierarchical summaries (last 30min raw + older)  │
│  │  - Participant tracking, topics, action items, decisions                 │
│  │  - LangGraph / custom state machine + LLM (local MLX-LM or frontier)     │
│  │  - Decision engine: when to speak, what to say, mode switching           │
│  └──────────────────────────────────────────────────────────────────────────┘
│                                  │                                            │
│                                  ▼ (when speak)                               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────────────┐ │
│  │   LLM Text   │──▶│   Streaming  │──▶│   Virtual Audio Device           │ │
│  │   Response   │   │   TTS        │   │   (BlackHole) → Chrome/Meet Mic  │ │
│  │   (structured)│  │   (ElevenLabs│   │   (or Cartesia / local)          │ │
│  └──────────────┘   │    Flash or  │   └──────────────────────────────────┘ │
│                     │    Cartesia) │                                         │
└─────────────────────┴──────────────┴─────────────────────────────────────────┘
```

**Data Flow**:
- Audio captured from Meet tab → streamed to backend.
- Backend emits timestamped, speaker-attributed utterances in real time.
- Agent brain updates context on every utterance (or batched) and periodically runs reasoning to decide actions.
- On "speak" decision → generate text → stream TTS audio → play directly to virtual mic device that Meet/Chrome is configured to use as input.

**Interactive Mode Switching**: Controlled by a combination of:
- Explicit user commands in Meet chat or via extension ("Hey agent, take over Q&A mode").
- Implicit triggers (prolonged silence, topic expertise match, low engagement signals, agenda item completion).
- Configurable agent "personality" prompt and participation aggressiveness slider.

---

## 3. Recommended Initial Technology Stack

**Prioritize local-first on M4 where latency/quality allows; use cloud for fastest POC velocity and highest realism.**

### Audio Capture
- **Chrome Extension** (Manifest V3, TypeScript + Vite or Plasmo framework for DX).
- `chrome.tabCapture` API for high-fidelity tab audio (preferred over desktopCapture for privacy and relevance).
- WebSocket binary streaming to local backend (16 kHz mono PCM16 recommended).

### STT + VAD + Diarization (Local on M4 — Primary Path)
- **MLX ecosystem** (Apple Silicon optimized, unified memory, excellent for 64 GB M4):
  - Transcription: `mlx-community/whisper-large-v3-turbo` (or quantized variants) — fast, accurate.
  - VAD / Endpointing: `mlx-community/silero-vad` (streaming capable).
  - Diarization: `mlx-community/diar_sortformer_4spk-v1` (or latest Streaming Sortformer SOTA) or pyannote ports.
  - Libraries: `mlx-audio`, `whisperlivekit` (if it supports MLX backend), or custom streaming pipeline using Simul-Whisper / AlignAtt concepts.
- Fallback / Quick POC: Deepgram Nova-3 or Flux (sub-300 ms, excellent diarization, voice agent optimized) or ElevenLabs Scribe v2 Realtime (~150 ms).

### LLM / Agent Brain
- **Primary for intelligence**: Frontier model via API (Claude 3.5/Opus/4-class, GPT-4o-class, or Grok) with structured outputs + tool calling. Excellent reasoning for meeting context.
- **Local option** (full offline/privacy): MLX-LM with large quantized models (Qwen2.5-72B, Llama-3.1-70B, or latest 2026 SOTA that fits in ~40–50 GB). Use for simpler decisions or hybrid routing.
- Orchestration: **LangGraph** (or custom state machine) for reliable agent workflows, memory, and mode switching. Pydantic for structured outputs.

### TTS (Super Realistic Voice — Critical for "live participant" feel)
- **Top recommendation**: **ElevenLabs** (Flash v2.5 / Turbo or Conversational AI stack) — consistently rated highest for human-like prosody, emotion, natural breathing, and voice cloning. Streaming support. Excellent for agentic use.
- **Ultra-low latency alternative**: **Cartesia Sonic 3** (~40–90 ms TTFA, state-space models, purpose-built for real-time agents).
- **Strong unified option**: Deepgram Aura-2 or ElevenLabs Scribe + Flash combo.
- Local (research only for POC): MLX audio ports or emerging high-quality local models; expect quality/latency gap vs. frontier cloud in 2026. Use only if privacy mandates it.

### Audio Output & Injection (macOS-specific)
- **Virtual audio driver**: **BlackHole** (free, open-source, widely used for exactly this: routing TTS to virtual mic for Zoom/Meet/Teams).
  - Or Loopback (paid, more polished routing rules).
- Python playback: `sounddevice` or `pyaudio` targeting the BlackHole device ID.
- Multi-output / aggregate device setup in **Audio MIDI Setup** app so TTS routes *only* to virtual mic (not speakers) to prevent echo/feedback. User uses headphones or mutes speakers.

### Backend & Orchestration
- **Python 3.12+** with `uv` or `conda` for env management.
- **FastAPI** + **WebSockets** (or Socket.IO) for bidirectional comms with extension.
- Async throughout for streaming (asyncio, anyio).
- Optional: LiveKit (if we later want internal media server abstraction) or just custom pipeline.
- State: In-memory + Redis (or SQLite + embeddings) for meeting context. Hierarchical summarization for long meetings.

### UI / Controls
- Chrome Extension sidebar (React/TS) showing:
  - Live attributed transcript.
  - Agent "thoughts" / reasoning trace (toggleable, for transparency).
  - Participation mode toggle + aggressiveness slider.
  - Quick actions (summarize now, ask this question, pause agent speaking).
- Optional lightweight desktop companion (Tauri) for advanced audio device management and persistent UI.

### Other
- Logging & observability: Structured logs with timestamps at every pipeline stage (critical for latency debugging).
- Testing audio: Use public multi-speaker datasets + self-recorded realistic meeting audio.
- Versioning: Pin all model weights and exact library versions in `requirements.txt` / `uv.lock`.

---

## 4. Phased Implementation Roadmap with Detailed Agent Steps

### Phase 0: Repository Bootstrap & Environment (1–2 days)
1. Initialize clean Git repo (or use existing empty one) with `.gitignore` (ignore model weights, recordings, `.env`, node_modules, etc.).
2. Create `README.md` with high-level goal, quickstart, and pointer to this `AGENTS.md`.
3. Set up Python environment: `uv init`, install core deps (fastapi, websockets, mlx, numpy, sounddevice, pydantic, langgraph, etc.). Create `pyproject.toml`.
4. Create Chrome extension skeleton: Use Plasmo (`npx plasmo init`) or Vite + CRXJS for best DX with hot reload and MV3 support. Set up TypeScript, Tailwind, shadcn/ui components for sidebar.
5. Define folder structure proposal (to be refined):
   ```
   /
   ├── extension/          # Chrome extension (Plasmo or src/)
   ├── backend/            # Python FastAPI + pipeline
   │   ├── audio/          # ingestion, VAD, STT, diarization
   │   ├── agent/          # LLM brain, LangGraph flows, memory
   │   ├── tts/            # TTS clients + playback
   │   ├── models/         # Pydantic schemas, prompts
   │   └── main.py
   ├── scripts/            # benchmarks, data prep, device setup
   ├── tests/              # unit + integration (pytest, with mocked streams)
   ├── docs/               # ADRs, architecture diagrams
   └── AGENTS.md
   ```
6. Create `.env.example` with keys for ElevenLabs/Deepgram/etc. and instructions for local-only mode.
7. Add pre-commit hooks (ruff, mypy, eslint) and CI skeleton (GitHub Actions for lint/typecheck).
8. **Success criterion**: Clean `git status`, `uv run backend` starts FastAPI without errors, extension loads unpacked in Chrome without console errors.

**Agent Tip**: Document any env gotchas for M4 (e.g., MLX requires specific macOS version or Xcode command line tools).

### Phase 1: Audio Capture from Google Meet Tab (POC — 3–5 days)
**Goal**: Reliably capture high-quality audio from an active Google Meet tab and stream it live to the local backend with minimal added latency.

**Detailed Steps**:
1. Research latest `chrome.tabCapture` + `chrome.tabCapture.capture` behavior in Manifest V3 (permissions, offscreen documents if needed for long-running capture, service worker limitations).
2. Implement background/service worker that:
   - Detects `meet.google.com` tabs (via `chrome.tabs.onUpdated` or declarative rules).
   - On user action ("Start Agent Session" button in popup or Meet page action), requests `tabCapture` permission and starts capture.
3. Convert captured `MediaStream` to processable audio:
   - Use `AudioContext` + `MediaStreamAudioSourceNode` + `ScriptProcessorNode` or `AudioWorklet` (preferred for performance) to downsample to 16 kHz mono and chunk into ~100–300 ms PCM buffers.
   - Or use `MediaRecorder` with `audio/webm;codecs=opus` then decode on backend (simpler but higher latency).
4. Establish WebSocket connection from extension (content script or offscreen) to `ws://localhost:8000/ws/audio`. Send binary audio chunks + metadata (tab ID, timestamp, meeting URL).
5. Handle edge cases: tab becomes inactive, user switches tabs, permission revocation, multiple Meet tabs, audio format negotiation.
6. Backend side: FastAPI WebSocket endpoint that receives chunks, converts to numpy float32 if needed, and forwards to a `AudioStreamManager` class (publish-subscribe or queue for downstream VAD/STT).
7. Add basic UI in extension popup/sidebar: "Capture Status: Connected / Streaming", latency indicator (time from chunk creation to backend receipt).
8. **Testing protocol**:
   - Join a real Google Meet with 2–3 participants (or use test meeting).
   - Speak for 30–60 seconds with natural pauses/overlaps.
   - Verify in backend logs: continuous chunks arriving, rough audio energy levels match speech, end-to-end chunk latency < 150 ms.
9. **Pitfalls to avoid**:
   - `tabCapture` only captures the tab's *output* audio (remote participants). Local mic is separate — good for our use case.
   - Service worker can be terminated; use `chrome.alarms` or offscreen document for persistence.
   - WebSocket reconnection logic + buffering on disconnect.
10. **Success criteria**:
    - Zero dropped chunks during 10+ minute meeting.
    - Backend can reconstruct intelligible audio from stream (save first 30s WAV for verification).
    - Extension shows live "Audio flowing" indicator.

**Agent Tip**: If tabCapture proves fragile, evaluate hybrid: extension for UI + macOS `AVAudioEngine` / `pyobjc` in a companion app for system audio capture (more reliable but captures everything).

### Phase 2: Real-Time STT + VAD + Speaker Diarization Pipeline (Core — 5–8 days)
**Goal**: Turn the raw audio stream into low-latency, timestamped, speaker-attributed text segments. Target partial results < 400 ms, final utterance < 1.2 s after speech ends.

**Detailed Steps**:
1. **Research & Benchmark Decision** (do this first):
   - Local MLX path (recommended long-term):
     - Install and test `mlx`, `mlx-audio`, `whisperlivekit` (or implement custom).
     - Benchmark `whisper-large-v3-turbo` (MLX) vs. Parakeet TDT (if NVIDIA but can run via compatibility) vs. Moonshine on sample multi-speaker audio.
     - Measure: RTF (real-time factor), time-to-first-partial, WER on held-out test set (use Common Voice or self-recorded), DER (diarization error rate) using pyannote metrics or simple overlap scripts.
   - Cloud quick-win path: Deepgram Nova-3/Flux or ElevenLabs Scribe v2 Realtime (both support streaming WebSocket, speaker diarization up to 16–32 speakers, low latency).
   - Decision matrix: Create table in `docs/adr-001-stt-choice.md`. Criteria: latency, WER/DER on meeting audio, cost (local wins), ease of streaming + diarization, M4 utilization.
2. Implement **VAD + endpointing** first (critical for low latency and natural turn-taking):
   - Use Silero VAD (MLX or ONNX). Run continuously on audio stream.
   - Detect speech start → begin buffering.
   - Detect speech end (silence > 300–600 ms configurable) → finalize utterance and trigger STT.
3. **Streaming / Chunked STT**:
   - For MLX Whisper: Implement or adapt streaming inference (chunk with overlap, use previous context for better accuracy, or use libraries supporting Simul-Whisper / AlignAtt policy).
   - Emit partial transcripts every ~150–300 ms during speech + final on endpoint.
   - Post-process: punctuation, capitalization, speaker assignment.
4. **Speaker Diarization integration**:
   - Online/streaming diarization is SOTA-challenging. Start with:
     - End-to-end models like Sortformer (MLX port) that output speaker labels per segment.
     - Or hybrid: transcription first → embedding extraction (speaker encoder) → online clustering (e.g., spectral or simple nearest-centroid with exponential decay for recency).
   - Maintain speaker map: "Speaker A (high pitch, started at 00:12)", allow later merging if consistent voiceprint.
   - For POC, 2–6 speakers is realistic; label unknown speakers generically and improve over time.
5. Define clean internal event schema (Pydantic):
   ```python
   class Utterance(BaseModel):
       start_ts: float
       end_ts: float
       speaker: str | int  # "Speaker_1" or stable ID
       text: str
       is_final: bool
       confidence: float
       raw_audio_ref: Optional[str]  # for debugging / replay
   ```
6. Build `TranscriptionPipeline` class that subscribes to audio chunks, runs VAD→STT→Diarization, and publishes `Utterance` events via internal queue or callback (for agent brain and extension UI).
7. Add comprehensive logging + optional WAV dumping of each finalized utterance for audit.
8. **Benchmark & tune**:
   - Create `scripts/benchmark_stt.py`: feed 5–10 minute realistic multi-speaker recording, measure pipeline latency distribution, WER, DER, CPU/GPU/RAM usage on M4.
   - Target: < 600 ms median from speech end to final utterance event; WER < 8–10% on clean meeting audio; DER < 15%.
9. **Hybrid mode**: Easy toggle to route audio to Deepgram instead for comparison or fallback.
10. **Success criteria**:
    - Live demo: Speak in Meet → within 1–2 seconds see attributed transcript appear in extension sidebar with correct speaker labels and low error rate.
    - Pipeline survives 30+ minute continuous meeting without memory leak or drift in speaker labels.

**Agent Tip**: Speaker diarization in pure streaming/online setting is still an active research area in 2026. For POC, "good enough" clustering + manual correction UI later is acceptable. Document limitations clearly.

### Phase 3: Realistic Voice Synthesis + Injection into Meeting (4–6 days)
**Goal**: When the agent decides to speak, generate natural-sounding audio and deliver it into Google Meet so other participants hear it as coming from a real attendee.

**Detailed Steps**:
1. **TTS Provider Selection & Integration**:
   - Primary: ElevenLabs — create account, select or clone a professional yet warm voice (male/female options, conversational style). Use their streaming WebSocket or HTTP chunked endpoint for lowest perceived latency.
   - Alternative: Cartesia Sonic for sub-100 ms TTFA testing.
   - Implement `TTSClient` abstract base + concrete classes. Support streaming playback (play first audio chunk immediately while more generates).
2. **Voice Design for Agent Persona**:
   - Define agent voice characteristics in prompt + voice settings: clear enunciation, moderate pace, slight warmth, professional but approachable. Avoid robotic or overly dramatic.
   - Support multiple voices or user-selectable "agent personality".
3. **Audio Playback to Virtual Mic**:
   - Install & configure **BlackHole** (or Loopback):
     - Download from existential.audio/blackhole.
     - In **Audio MIDI Setup** (macOS app): Create Multi-Output Device including BlackHole + your real speakers (or just BlackHole). Create Aggregate Device if needed.
     - In Python: Use `sounddevice.query_devices()` to find BlackHole device ID. Open output stream to it (`sounddevice.OutputStream(device=..., channels=1, samplerate=24000 or 44100)`).
   - **Critical routing for no echo**:
     - Configure so TTS audio goes *only* to BlackHole (virtual mic input for Meet).
     - Do **not** play to hardware speakers simultaneously, or use headphones + separate routing.
     - Test: Play test tone from Python → it should appear in Meet when mic is set to BlackHole, but not come out of your speakers.
4. **Integration with Agent**:
   - When `speak(text)` action is triggered: call TTS → receive audio chunks (numpy or bytes) → immediately start playing to BlackHole stream while buffering more.
   - Support interruption/barge-in detection: While agent is speaking, keep VAD running on input. If human speech detected above threshold, pause or fade TTS and yield turn (advanced but high value for naturalness).
5. **Chrome/Meet Mic Configuration**:
   - Document exact steps for user: In Meet, click mic icon → settings → select the BlackHole / Aggregate device as microphone. Grant permission once.
   - Extension can attempt to guide or (advanced) use Chrome settings automation (limited).
6. **Testing full audio loop**:
   - End-to-end: Human speaks in Meet → transcribed → agent decides to respond → TTS plays → other participants (or second Meet window) hear the agent's voice clearly, with natural prosody and low delay.
   - Measure: Time from LLM text ready → first audio out of virtual mic.
7. **Pitfalls**:
   - Sample rate / channel mismatch between TTS output and BlackHole (resample with `scipy` or `sounddevice`).
   - macOS permissions for microphone access (Chrome needs it for the virtual device).
   - Feedback loops if routing is wrong.
   - TTS latency variability under load.
8. **Success criteria**:
   - Blind listening test: 3+ people cannot reliably distinguish agent voice from human in short exchanges.
   - Full loop latency (human stop speaking → agent starts audible reply) < 2.5 s median in good conditions.
   - No audio artifacts, dropouts, or echo in 10-minute test meeting.

**Agent Tip**: If full voice injection proves too fragile for initial POC, implement **text-first mode** in parallel: Agent outputs to extension sidebar + optional "Read Aloud" button that plays TTS locally for the *user only*. This still delivers huge value and can be the default while voice routing is perfected.

### Phase 4: Agentic Conversation Engine, Context & Decision Making (6–10 days — Most Complex)
**Goal**: Build an intelligent agent that maintains meeting state, reasons about when/how to participate, and generates contextually appropriate contributions (especially questions).

**Detailed Steps**:
1. **Define Agent Persona & Core Prompt**:
   - Create detailed system prompt: role ("expert meeting participant and facilitator"), goals (help team reach clarity, surface hidden assumptions, drive to decisions, keep concise), constraints (never speak > 25 seconds without pause, wait for natural turn end, be curious not pushy, adapt to meeting tone).
   - Support mode-specific prompts: Passive Listener, Active Collaborator, Q&A Facilitator.
2. **Context & Memory Architecture**:
   - `MeetingContext` Pydantic model: participants (list with stable IDs + inferred names/roles), rolling raw transcript window (last 8–15 min), hierarchical summary (LLM-generated every 5–10 min or on topic shift), open_questions, decisions, action_items, current_agenda_item, agent_notes.
   - Use vector store (local Chroma or simple FAISS with sentence-transformers/MLX embeddings) for semantic retrieval of past relevant utterances.
   - On every finalized `Utterance`: append, trigger light update (extract entities if obvious), and (async) run summarizer if window full.
3. **Decision Engine (LangGraph or Custom State Machine)**:
   - Nodes: `ingest_utterance` → `update_memory` → `reason_and_decide` → `generate_response` (if speak) or `do_nothing`.
   - Use LLM structured output (Pydantic model or JSON schema) for decisions:
     ```python
     class AgentDecision(BaseModel):
         action: Literal["listen", "speak", "ask_question", "summarize", "note_action_item"]
         text: Optional[str] = None
         confidence: float
         reasoning: str  # internal trace for UI/debug
         target_speaker: Optional[str] = None
     ```
   - Triggers for `reason_and_decide`:
     - On every utterance end (or every N seconds during silence).
     - After long silence (> 8–12 s).
     - On explicit address ("Agent, what do you think?").
     - Periodically for proactive mode.
   - Rules encoded in prompt + few-shot examples: Detect complete thoughts, avoid interrupting mid-sentence, match energy of discussion, ask one focused question at a time.
4. **Mode Switching Logic**:
   - Implement `ParticipationMode` enum/state.
   - UI controls + LLM can propose mode changes.
   - In Active mode: bias toward asking clarifying or forward-looking questions when context allows.
   - In Q&A mode: wait for questions directed at agent or surface when topic matches.
5. **LLM Integration**:
   - Abstract `LLMClient` supporting multiple backends (MLX-LM local, Anthropic, OpenAI, xAI/Grok, etc.).
   - Always use structured outputs + temperature 0.3–0.7 depending on task (lower for decisions, higher for creative phrasing).
   - Context window management: Truncate oldest raw transcript, keep recent + summary + structured state. Target < 60k–100k tokens effective.
6. **Response Generation Quality**:
   - Generate text optimized for TTS (natural spoken language, short paragraphs, strategic pauses via punctuation or SSML if supported).
   - Post-process: Remove meta phrases ("As the AI..."), keep first-person consistent if persona uses it.
7. **Testing & Evaluation**:
   - Create synthetic meeting transcripts + gold "good agent responses".
   - Automated: Check decision quality, hallucination rate, adherence to constraints.
   - Human eval: Run full meetings, rate (1–5): naturalness of timing, helpfulness of contributions, voice realism, overall "would you want this colleague in your meeting?".
8. **Success criteria**:
   - In 3+ test meetings, agent makes 2–5 contributions that feel timely and add value (e.g., surfaces an unasked question, clarifies ambiguity, proposes next step) without more than 1–2 awkward interruptions or irrelevant comments.
   - Context remains coherent after 45+ minute meeting.

**Agent Tip**: Start simple (rule-based triggers + LLM response generation) before full LangGraph. Add complexity only after basic loop works. Log every decision + full prompt/context for debugging "why did it say that?".

### Phase 5: UI/UX, Full Integration, Testing & Polish (5–7 days)
1. Flesh out Chrome extension sidebar:
   - Real-time transcript feed (virtualized list, color-coded by speaker, auto-scroll with pause button).
   - Agent panel: Current mode, last decision reasoning (collapsible), quick controls.
   - Settings: Voice selection, participation aggressiveness (slider 0–100%), allowed topics or guardrails, local-only vs hybrid processing toggle.
2. Add visual/audio cues: Subtle "Agent is listening" pulsing icon in Meet tab (content script injection, careful with Meet DOM changes), "Agent speaking" indicator.
3. Implement manual override: "Speak this text as agent" button that bypasses decision engine (great for testing and user trust).
4. End-to-end testing harness:
   - Scripted meetings with known ground truth.
   - Automated latency measurement across full pipeline (capture → STT final → decision → TTS first audio).
   - Chaos testing: sudden speaker changes, long silences, overlapping speech, poor audio quality.
5. Error handling & UX:
   - Graceful degradation: If STT confidence low → flag in UI, fall back to more conservative participation.
   - One-click "Emergency Stop Agent Speaking".
   - Clear privacy banner: "This meeting audio is processed locally on your M4 Mac. Nothing is sent to cloud unless you enable hybrid mode."
6. Documentation: Update README with setup video/script (or detailed written), troubleshooting (common BlackHole issues, permission dialogs), example prompts.
7. **Success criteria**:
   - Non-technical user can follow setup instructions and have a working session in < 15 minutes.
   - Full pipeline survives real 30–60 min meeting with < 5% manual intervention needed.
   - Positive qualitative feedback from 2–3 internal test users on naturalness and usefulness.

### Phase 6: Optimization, Robustness & POC Hardening (Ongoing)
- Latency profiling & optimization at every stage (use `cProfile`, MLX tracing, WebSocket message timing).
- Memory management for long meetings (aggressive summarization, utterance pruning).
- Improve diarization with voice fingerprinting across sessions if user reuses agent.
- Add basic tools to agent (web search for facts, internal knowledge retrieval) once conversational core is solid.
- Packaging: Script to bundle extension + one-command backend launch + BlackHole check.
- Metrics dashboard (optional): Simple Streamlit or extension page showing pipeline health, average latencies, participation stats.
- Security/Compliance: Audit for PII leakage, add meeting-level consent recording toggle (with transcript export option).

---

## 5. Guidelines for All Agents Working on This Project

### Research Protocol
- Before implementing any component, spend time benchmarking 2–3 realistic options using actual meeting audio.
- Prefer local MLX solutions on M4 hardware for latency and privacy; justify cloud choices with data (e.g., "ElevenLabs quality gap too large for POC realism goal").
- Always record exact versions, prompts, and benchmark numbers in `docs/benchmarks/` or ADRs.

### Coding Standards
- Type hints everywhere (Python 3.12+). Use Pydantic v2 for all I/O and state.
- Async-first for all I/O and streaming paths.
- Modular design: Each major capability (STT, TTS, AgentBrain, AudioRouter) behind clean interfaces so they can be swapped.
- Comprehensive logging with context (meeting_id, utterance_id, stage).
- Tests: Aim for >70% coverage on core pipeline logic. Use `pytest` + `pytest-asyncio`. Mock audio streams and LLM responses.

### When Things Are Hard (Especially Audio Injection & Natural Turn-Taking)
- Document attempts thoroughly.
- Provide fallback paths (text sidebar + manual speak is a valid valuable POC).
- Prioritize "works reliably in controlled conditions" over "perfect in all edge cases" for initial POC.

### Evaluation Mindset
- Quantitative: Latency distributions, WER, DER, decision accuracy vs. gold labels.
- Qualitative: "Does this feel like a helpful, natural colleague or a bot that occasionally blurts?" Run real meetings with colleagues and collect structured feedback.
- Latency budget example (stretch goal):
  - VAD + chunk ready: < 100 ms
  - STT partial/final: < 500 ms
  - LLM decision + generation: < 800 ms (local) or < 400 ms (frontier API)
  - TTS first audio: < 150 ms
  - **Total human stop → agent audible start: < 2 s ideal, < 3 s acceptable for POC**

### Documentation & Knowledge Sharing
- Every significant decision or benchmark → ADR in `docs/adr-XXX-*.md`.
- Update this `AGENTS.md` after each phase with "What we learned" and revised estimates.
- Keep prompts, system instructions, and example decisions in version control (they are core IP).

### Safety, Ethics & User Trust
- The agent must **never** feel deceptive. Clear visual/audible indicators that an AI is active and participating.
- User must have instant, obvious control to mute/disable the agent's voice or the entire system.
- Default to local processing. Cloud features opt-in with clear disclosure.
- Respect meeting sensitivity: No auto-recording or cloud upload without explicit per-meeting consent UI.

---

## 6. Getting Started Checklist for a New Agent

1. Read this entire `AGENTS.md` and the original project notes.
2. Run `git status` and explore current structure (or bootstrap per Phase 0).
3. Set up your M4 environment and verify MLX works (`python -c "import mlx; print(mlx.core.default_device())"` should show GPU or CPU appropriately).
4. Pick a phase or subtask that matches your strengths (e.g., audio pipeline, LLM agent logic, Chrome extension).
5. Create a branch named after the phase/task.
6. Implement incrementally with tests and frequent commits.
7. When blocked or unsure, propose approach in discussion and reference specific sections of this doc.
8. Upon completing a meaningful chunk: Update AGENTS.md, add ADR if decision was non-obvious, run full pipeline test, and share results (latency numbers, demo notes, lessons).

**Current Priority (as of initial creation)**: Phase 0 + Phase 1 (get reliable audio flowing from Meet tab into backend) + basic VAD/STT POC in Phase 2. Voice injection and full agent brain can follow once the foundation is solid.

---

This document will evolve. Treat it as the single source of truth for how we build this ambitious but achievable system. The end vision — a true agentic colleague that listens, understands, and contributes naturally in meetings — is within reach with disciplined execution on the M4 hardware and careful integration of 2026-era audio AI components.

Let's build something remarkable. Start with small, verifiable wins in audio capture and transcription, then layer on the intelligence and voice.

**Questions or proposed changes to this plan?** Open an issue or discussion referencing the relevant section.

---

## Implementation Notes

### 2026-05-05: Phase 0/1 Bootstrap

- Bootstrapped the Python backend with `uv`, FastAPI, Pydantic v2 models, structured audio packet parsing, session statistics, and optional first-N-second WAV dumps for Phase 1 verification.
- Bootstrapped a Manifest V3 Chrome extension with Vite, TypeScript, React, Tailwind, local shadcn-style UI primitives, popup controls, side-panel controls, and a Meet status badge content script.
- Chose the MV3 capture architecture documented in `docs/adr-001-tab-capture-architecture.md`: user-gesture UI obtains a `chrome.tabCapture.getMediaStreamId()`, the service worker coordinates an offscreen document, the offscreen document owns Web Audio and streams PCM16 packets to the local backend.
- Added `scripts/send_test_audio.py` so backend ingestion can be verified without Chrome or Google Meet.
- Added initial CI and pre-commit gates for backend lint/typecheck/tests and extension lint/typecheck/build.
