# Remaining Functionality Requirements Analysis

Date: 2026-06-15

## Current Implemented Baseline

The stack already has the core real-time plumbing needed for a live Google Meet POC:

- Chrome extension capture from Meet tab audio and WebSocket streaming to the backend.
- Backend audio queue, telemetry, endpointing consumer, VAD provider selection, and health APIs.
- Offline and live STT paths with MLX Whisper support and recent transcript exposure at `/api/stt`.
- Replaceable diarization provider seam with the current heuristic acoustic provider, a
  `single_speaker` smoke-test provider, corrected speaker-label metadata, and visible
  provider/confidence/merge-state transcript fields.
- TTS provider abstraction with fake, macOS `say`, ElevenLabs, and Cartesia adapters.
- Audio playback path through PortAudio, with BlackHole visible as `BlackHole 2ch` on this Mac.
- Manual TTS controls and barge-in interruption on human `speech_start`.
- Initial Erica meeting agent state machine with lifecycle, participation modes, runtime states,
  candidate interventions, recent utterances, participants, lightweight requirements, questions,
  and decisions.
- Deterministic rolling context checkpoints that compress recent utterance windows into status and
  final meeting summary artifacts.
- Immediate current-topic tracking from explicit topic transitions and requirement-like utterances.
- Synthetic Phase 4 behavior eval harness with JSON/Markdown reports for structured memory,
  candidate generation, dedupe, parked topics, risks, and context checkpoints.
- Extension cards for capture, transcript, consumer health, voice, and Erica controls.

The current Erica implementation is intentionally deterministic and in-memory. It can store direct
address candidates, auto-queue direct-address speech in permitted modes, and create silent
clarifying-question candidates from requirement-like statements.

## Remaining Product Requirements

### R1. LLM-Backed Meeting Reasoning

Erica needs a bounded reasoning layer that uses meeting state to choose and draft useful
contributions. The deterministic state machine must remain the authority for mode, lifecycle,
cooldown, health, and turn-taking.

Required capabilities:

- Add an `LLMClient` interface with deterministic fake provider tests. Implemented with
  `FakeLLMClient` and structured `AgentReasoningDecision`.
- Add configured cloud/local providers behind environment flags after provider selection.
  Implemented for OpenAI Responses API structured output behind `PROOF_AGENT_LLM_PROVIDER=openai`;
  implemented for local MLX-LM behind `PROOF_AGENT_LLM_PROVIDER=mlx_lm` with lazy model loading and
  the same JSON decision contract.
- Support live prompt tuning without code edits. Implemented with optional
  `PROOF_AGENT_LLM_REASONING_PROMPT_SUFFIX`, `PROOF_AGENT_LLM_DIRECT_ANSWER_PROMPT_SUFFIX`, and
  `PROOF_AGENT_LLM_CONTEXT_SUMMARY_PROMPT_SUFFIX` environment overrides that append to the default
  system prompts.
- Support prompt and behavior tuning when Meet audio or STT is unavailable. Implemented with
  `POST /api/agent/transcript`, which injects finalized manual utterances into Erica through the
  same transcript observation path used by live STT.
- Use configured LLM providers for direct-address answers while preserving deterministic fallback.
  Implemented for fake and OpenAI clients with provider-error fallback.
- Generate structured decisions such as `listen`, `draft_candidate`, `speak_now`, `summarize`,
  `capture_decision`, and `ask_clarifying_question`. Implemented for fake-first and OpenAI-backed
  candidate decisions, including summary checkpoints, model-captured decisions, and operator-review
  mode-change suggestions.
- Include recent utterances, requirements, open questions, decisions, mode, and cooldown state in
  prompts. Implemented as `ReasoningContext` with rolling context checkpoints for the fake-first
  and OpenAI seams; current topic is also included when available.
- Store the model's short internal reason on the candidate for debug UI. Implemented through
  candidate `reason`.
- Expose bounded provider-call telemetry for prompt/provider tuning. Implemented through
  `llm_call_traces` with operation, provider class, success/error, latency, and short previews for
  reasoning, direct-answer, and context-summary calls.
- Fail closed: if LLM output is invalid or slow, Erica should keep listening and expose `last_error`.
  Implemented for injected reasoning clients.

Acceptance criteria:

- Direct questions to Erica produce contextual answers instead of the current placeholder text.
  Implemented with deterministic memory answers and optional LLM-backed answers when configured.
- Requirement-like utterances produce higher quality clarifying questions with explicit rationale.
  Implemented for deterministic fake decisions and configurable OpenAI prompt suffixes; live prompt
  quality still needs validation in Meet.
- Unit tests cover valid output, invalid JSON, provider timeout, and disabled-provider behavior.
  Implemented for valid fake output, malformed candidate decisions, provider timeout,
  no-provider deterministic fallback, OpenAI request shape, OpenAI nested output parsing, and
  missing API keys.

### R2. Turn-Taking and Autonomous Facilitation Policy

Erica has an initial deterministic path from candidate detection to speech in `facilitator` mode.
Requirement-like utterances can move to `waiting_for_turn`, and VAD `speech_end` can trigger
proactive clarification when mode, aggressiveness, cooldown, and silence policy allow it.

Required capabilities:

- Add minimum silence threshold and cooldown settings. Implemented for deterministic policy and
  runtime-configurable through `/api/agent/settings` plus side-panel controls.
- Add `waiting_for_turn` transition for proactive candidates. Implemented.
- Allow LLM/classifier logic to suggest a participation mode change without changing mode
  autonomously. Implemented as `mode_change` candidates that require operator apply.
- Support explicit in-meeting control commands. Implemented for addressed utterances that switch
  Erica's participation mode or end the meeting while recording the command utterance and avoiding
  a direct-answer candidate.
- Only auto-speak proactive candidates when VAD indicates a safe gap and mode/aggressiveness allow
  it. Implemented for clarifying-question candidates.
- Suppress proactive speech when TTS is unavailable, STT is unhealthy, capture is stopped, or meeting
  lifecycle is not `in_meeting`. Implemented through `AgentReadiness` blockers derived from active
  sessions, audio consumer health, STT health, and TTS health.
- Keep manual candidate approval available in all speaking-capable modes.

Acceptance criteria:

- In `passive` and `scribe`, proactive candidates never speak automatically.
- In `facilitator`, high-confidence clarifying questions can speak after a configurable silence gap.
- Addressed commands such as "Erica, switch to facilitator mode" update mode immediately, and
  "Erica, end meeting" generates the summary artifact.
- Any human speech during TTS interrupts playback and moves Erica to `interrupted` or `cooldown`.

### R3. TTS Completion and Runtime State Feedback

Erica currently marks itself as `speaking` when speech is queued, but TTS completion is not wired
back into the agent state.

Required capabilities:

- Add a TTS completion callback or event subscription from `TtsOrchestrator` to
  `MeetingAgentOrchestrator`. Implemented through the `TtsOrchestrator` result handler in
  `backend.main`.
- Move `speaking -> cooldown -> idle_listening` based on actual speech completion and elapsed
  cooldown. Implemented through `observe_speech_result` and status-time cooldown expiry refresh.
- Expose current/last speech job IDs in agent status for debugging. Implemented as
  `active_speech_job_id` and `last_speech_job_id`.
- Ensure interruption and failed TTS jobs clear or update runtime state predictably. Implemented for
  completed, interrupted, and error speech results.

Acceptance criteria:

- `/api/agent` reflects `speaking` only while the TTS worker is actively speaking.
- Completed speech updates `last_agent_speech_at_ms`, enters cooldown, then expires back to
  `idle_listening` after the configured cooldown.
- Failed speech records an error and returns to `candidate_intervention` or `idle_listening`.

### R4. Meeting Memory Depth and Requirements Artifacts

The current memory records are useful placeholders but not enough for a requirements-gathering
companion.

Required capabilities:

- Expand requirement records with actor, goal, behavior, constraints, priority, acceptance criteria,
  owner, source utterances, and status. Implemented as deterministic field extraction for common
  requirement phrasing, including common acceptance-criteria and definition-of-done phrases.
  LLM-backed refinement is implemented as a bounded `requirement_refinement` patch that can enrich
  an existing requirement without creating ungrounded new records.
- Track unresolved questions and link them to requirements when possible. Implemented with
  deterministic related requirement IDs for overlapping human questions while generated acceptance
  prompts remain scoped to the requirement record.
- Track action items and risks.
- Update memory lifecycle state as the meeting progresses. Implemented for deterministic
  answer-like utterances closing related open questions, confirmation phrases marking matching
  decisions as confirmed, and completion phrases marking matching action items as completed.
- Merge duplicate requirements and decisions across a meeting. Implemented for deterministic
  normalized matches across requirements, questions, decisions, action items, risks, and parked
  topics, including conservative semantic keys for common equivalent phrasing.
- Generate an end-of-meeting summary with requirements, decisions, open questions, action items, and
  parked topics. Implemented for requirements, decisions, open questions, action items, risks, and
  candidate interventions, including parked topics.
- Add export endpoint for Markdown and JSON artifacts. Implemented as `/api/agent/summary` and
  `/api/agent/summary.md` for the current in-memory summary.
- Maintain rolling transcript checkpoints for longer meetings. Implemented as
  `MeetingContextSummary` records with deterministic fallback and optional LLM-backed
  `summarize_context` generation from recent utterances plus structured memory; deeper
  hierarchical summarization remains.
- Track current topic for immediate context anchoring. Implemented in `/api/agent`, final summaries,
  LLM reasoning context, and the extension side panel.

Acceptance criteria:

- Ending a meeting produces a stable summary artifact. Implemented with JSON and Markdown
  persistence under `PROOF_AGENT_SUMMARY_DIR`.
- Requirements preserve source utterance IDs for traceability.
- Open questions preserve related requirement IDs when a question overlaps a captured requirement.
- Answered questions, confirmed decisions, and completed action items preserve the closing
  utterance ID for traceability and are labeled in status/UI/summary artifacts.
- Current topic updates immediately from captured requirements and explicit topic transitions.
- Acceptance criteria extracted from requirement statements are preserved in status, summaries, and
  side-panel requirement details.
- LLM requirement refinements can add owner, priority, status, constraints, acceptance criteria, and
  open questions to an existing requirement while preserving source traceability.
- LLM context summaries can produce richer rolling checkpoints while preserving deterministic
  fallback behavior for provider failures.
- Repeated mentions update existing records instead of always appending duplicates. Implemented for
  normalized exact matches and conservative semantic matches while preserving
  `source_utterance_ids`; embedding/LLM near-duplicate merging remains.

### R5. Extension UX for Remaining Agent Workflows

The extension currently exposes counts and candidate interventions. The remaining workflows need
review and operator controls.

Required capabilities:

- Add sections for requirements, open questions, and decisions, not just counts.
  Implemented for compact side-panel review sections.
- Add candidate dismiss/approve controls and show whether a candidate is safe to auto-speak.
- Show Erica's current reasoning/rationale in a compact debug panel.
  Implemented with bounded `/api/agent` `reasoning_traces` and a side-panel reasoning section
  showing recent actions, scores, gating state, rationales, and fail-closed errors.
- Surface STT/TTS/agent health blockers in a single readiness summary.
- Make aggressiveness affect backend policy rather than staying only in local extension settings.

Acceptance criteria:

- Operator can review, speak, or dismiss a candidate from the side panel.
- Operator can apply a proposed mode-change candidate from the side panel.
- Operator can inspect captured requirements and open questions during a live meeting.
- Operator can inspect recent reasoning traces without opening backend logs.
- Operator can inspect recent provider-call latency and errors without opening backend logs.
- Backend receives and persists participation/aggressiveness settings for the active meeting.

### R6. Diarization Upgrade

The heuristic speaker attribution is acceptable for proving the UI and agent loop, but not for the
POC success criterion of speaker identification.

Required capabilities:

- Add a replaceable diarization provider interface next to `HeuristicSpeakerDiarizer`.
  Implemented as `DiarizationProvider` plus `PROOF_DIARIZATION_PROVIDER`, with
  `heuristic_acoustic` and `single_speaker` providers.
- Benchmark Sortformer or speaker-embedding online clustering on captured meeting audio. The
  benchmark/report harness is implemented as `uv run benchmark-diarization` for `/api/stt` snapshots
  or JSONL rows with corrected labels/reference speakers; real model integration and captured
  multi-speaker benchmark data remain.
- Expose diarization provider, confidence, and merge state in transcript payloads.
  Implemented in `/api/stt` and final `utterance` payloads.
- Add a manual speaker-label correction hook for the extension. Implemented as
  `POST /api/stt/speakers/label` plus side-panel save/clear controls on transcript rows for future
  transcript assignments.

Acceptance criteria:

- Diarization provider can be enabled by environment flag for the implemented providers; a real
  Sortformer or embedding provider still needs model integration and benchmarking.
- Benchmark report includes approximate DER or a simpler speaker consistency metric. Implemented as
  label-based speaker consistency, error proxy, provider/merge-state counts, and unlabeled churn
  rate fallback.
- Extension can display human-readable participant labels when available. Implemented in transcript
  rows using `speaker_label` with raw speaker ID preserved as title metadata.

### R7. Live Meeting Validation

The system has strong unit and smoke coverage, but the remaining product risk is live-meeting
behavior.

Synthetic behavior validation is now available through `uv run evaluate-agent --strict`; it does
not replace a live Google Meet validation pass. A stronger local Phase 4 preflight is available
through `uv run verify-phase4 --strict`; it verifies direct-address speech enqueueing, spoken mode
controls, facilitator auto-speak after silence, structured memory, provider-call telemetry, and
summary generation before joining Meet.
`uv run phase4-live-runbook` writes a machine-specific checklist with backend environment, Meet
setup, live checks, and evidence commands for the run.
`uv run verify-phase4-live-backend --strict` verifies that the launched backend reports live STT,
TTS playback, and the expected virtual audio output device before joining Meet.
After live validation, `uv run phase4-live-bundle` captures runtime snapshots and creates a
Markdown/JSON evidence artifact under `docs/benchmarks/` with the acceptance checks, latency, notes,
and linked runtime artifacts. `uv run capture-phase4-snapshot` and `uv run phase4-live-report`
remain available for separated capture/report workflows.

Required capabilities:

- Run the backend with `PROOF_STT_ENABLED=true`, Silero VAD, MLX Whisper, macOS or cloud TTS, and
  `PROOF_TTS_OUTPUT_DEVICE="BlackHole 2ch"`.
- Run `uv run evaluate-agent --strict`, `uv run verify-phase4 --strict`, and
  `uv run verify-phase4-live-ready --strict` before live validation.
- Generate the operator checklist with `uv run phase4-live-runbook` before live validation.
- After backend launch, run `uv run verify-phase4-live-backend --strict` before joining Meet.
- Join a Google Meet with the extension loaded and Meet microphone set to BlackHole.
- Verify remote audio capture, transcript generation, Erica candidate creation, manual speech, and
  direct-address speech.
- Capture runtime snapshots and latency/failure observations with `uv run phase4-live-bundle`, or
  with `uv run capture-phase4-snapshot` followed by `uv run phase4-live-report`.

Acceptance criteria:

- Other meeting participants can hear Erica through the BlackHole microphone route.
- Transcript appears in the extension while capture is active.
- Directly addressing Erica in `assistant` mode results in an audible answer.
- No feedback loop or repeated self-interruption occurs during a 10-minute test.
- A `docs/benchmarks/phase-4-live-google-meet-validation-*.md` report records the pass/fail
  evidence and links capture/session, preflight, agent summary, STT, and TTS status artifacts when
  available.

## Dependencies and Environment

Available now:

- Apple Silicon MLX dependencies are pinned in `uv.lock`.
- BlackHole output device is visible to PortAudio as `BlackHole 2ch`.
- Local macOS TTS provider is available without cloud credentials.
- ElevenLabs and Cartesia adapters exist but require API credentials and real voice IDs.

Needed for remaining work:

- Decision on first LLM provider for live reasoning. OpenAI is wired first behind env flags.
- API keys and model configuration if using cloud LLM or premium TTS.
- Real Google Meet test session with at least one remote listener for voice-injection validation.
- Representative multi-speaker meeting recordings for diarization and agent behavior benchmarks.

## Recommended Next Implementation Order

1. Wire TTS completion back into Erica runtime state.
2. Add candidate approve/dismiss and backend aggressiveness settings.
3. Add a fake-first `LLMClient` and contextual direct-answer generation.
4. Add guarded facilitator auto-speak after silence and cooldown checks.
5. Add requirements/open-question/decision detail UI and exportable meeting summary.
6. Upgrade diarization behind a provider interface.
7. Run and document a live Google Meet validation pass.

This order improves correctness and observability before adding autonomous speech, which keeps the
system controllable while the agent gets more capable.
