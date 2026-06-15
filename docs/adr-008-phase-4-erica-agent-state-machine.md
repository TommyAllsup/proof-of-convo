# ADR 008: Phase 4 Erica Agent State Machine

Date: 2026-06-15

## Status

Proposed for Phase 4 design discussion. No server code has been changed for this ADR.

## Context

Proof of Conversation has the major audio plumbing required for a live meeting participant:

- Google Meet tab audio capture from the Chrome extension.
- Backend audio queueing, telemetry, VAD, endpointing, live STT, and heuristic speaker labels.
- Manual TTS and virtual microphone playback through the backend `TtsOrchestrator`.
- Barge-in interruption where human `speech_start` events stop current TTS playback.

The next product step is to make the meeting companion active. The companion will be called **Erica**.
Erica's purpose is not to be a generic chatbot in the meeting; Erica should act as a requirements-gathering companion that listens, tracks context, answers when addressed, and helps refine requirements at useful moments.

The immediate design challenge is deciding when Erica should remain passive and when Erica should participate. That decision needs to be explicit, observable, and testable before the backend starts generating autonomous meeting speech.

## Decision Direction

Introduce a backend-side meeting agent controller, tentatively named `MeetingAgentOrchestrator` or `ConversationAgent`, that consumes finalized `LiveTranscript` events and owns Erica's participation state.

The controller should separate **participation mode** from **runtime state**.

### Participation Modes

Participation mode is operator/user configured. It describes Erica's behavioral stance.

| Mode | Meaning |
|---|---|
| `off` | Erica does not reason or speak. Audio/STT may still run for diagnostics. |
| `passive` | Erica tracks transcript, requirements, decisions, and questions, but does not speak automatically. |
| `assistant` | Erica answers when explicitly addressed and may surface low-risk help. |
| `facilitator` | Erica can proactively ask clarifying questions and help drive requirements discovery. |
| `qa` | Erica primarily answers direct questions and avoids proactive facilitation. |
| `scribe` | Erica focuses on summaries, decisions, action items, and minimal clarification. |

Initial implementation should probably ship only `off`, `passive`, `assistant`, and `facilitator`, while leaving `qa` and `scribe` as near-term extensions if they complicate the first state machine.

### Meeting Lifecycle States

Meeting lifecycle state describes where Erica is in the session lifecycle. This should be separate from participation mode and runtime activity because beginning and ending a meeting involve setup/teardown behaviors rather than just conversational turn-taking.

| Lifecycle State | Meaning |
|---|---|
| `not_in_meeting` | No active meeting session is attached. Erica should not analyze or speak. |
| `joining_meeting` | Audio/STT/TTS readiness is being checked and the meeting session is being initialized. |
| `meeting_started` | Erica has detected or been told that the meeting is active; context capture may begin. |
| `in_meeting` | Normal meeting operation. Runtime state controls whether Erica listens, thinks, or speaks. |
| `ending_meeting` | Erica is preparing final summary artifacts, decisions, requirements, open questions, and action items. |
| `meeting_ended` | The meeting is over; Erica should stop speaking, finalize artifacts, and release transient session state. |

Initial transitions can be manual/API-driven rather than inferred automatically:

```text
not_in_meeting → joining_meeting → meeting_started → in_meeting → ending_meeting → meeting_ended → not_in_meeting
```

Later, lifecycle transitions can be inferred from extension capture start/stop, Meet tab connection health, participant activity, or explicit phrases such as "Erica, start the meeting" and "Erica, end the meeting."

### Runtime States

Runtime state describes what Erica is doing right now within an active meeting lifecycle.

| State | Meaning |
|---|---|
| `idle_listening` | Erica is listening and accumulating context. |
| `candidate_intervention` | Erica has identified something potentially useful to say, but has not committed to speaking. |
| `waiting_for_turn` | Erica wants to speak but is waiting for a safe opening. |
| `thinking` | Erica is classifying, planning, or generating a response. |
| `speaking` | Erica has handed speech to TTS and should avoid overlapping humans. |
| `interrupted` | Human speech began while Erica was speaking. |
| `cooldown` | Erica recently spoke or was interrupted and should avoid immediate follow-up. |
| `manual_override` | A user/operator explicitly requested speak, stop, or mode change. |

Keep this runtime enum small. Requirements tracking, topic tracking, candidate questions, and meeting lifecycle should be modeled as structured context or separate lifecycle state, not as a large number of top-level runtime states.

## State Machine Sketch

The full controller should be modeled as two coordinated state machines:

1. **Meeting lifecycle state machine**: whether Erica is before, inside, or after a meeting.
2. **Runtime participation state machine**: what Erica is doing during the active meeting.

### Meeting Lifecycle Sketch

```text
┌────────────────┐
│ not_in_meeting │
└───────┬────────┘
        │ extension capture starts / manual begin
        ▼
┌────────────────┐
│ joining_meeting│
└───────┬────────┘
        │ audio + STT readiness confirmed
        ▼
┌────────────────┐
│ meeting_started│
└───────┬────────┘
        │ initialize meeting context
        ▼
┌────────────┐
│ in_meeting │
└─────┬──────┘
      │ manual end / capture stop / end phrase
      ▼
┌────────────────┐
│ ending_meeting │
└───────┬────────┘
        │ summaries + artifacts finalized
        ▼
┌───────────────┐
│ meeting_ended │
└───────┬───────┘
        │ cleanup complete
        ▼
┌────────────────┐
│ not_in_meeting │
└────────────────┘
```

### Runtime Participation Sketch

```text
┌────────────────┐
│ idle_listening │
└───────┬────────┘
        │ finalized transcript
        ▼
┌──────────────────────┐
│ update_conversation  │
└───────┬──────────────┘
        │
        ├── no action ───────────────▶ idle_listening
        │
        ├── direct question to Erica ▶ thinking
        │
        ├── requirement ambiguity ───▶ candidate_intervention
        │
        └── manual speak trigger ────▶ thinking

┌────────────────────────┐
│ candidate_intervention │
└───────┬────────────────┘
        │ confidence high + mode allows speech
        ▼
┌──────────────────┐
│ waiting_for_turn │
└───────┬──────────┘
        │ silence/end-of-turn detected
        ▼
┌──────────┐
│ thinking │
└────┬─────┘
     │ response generated
     ▼
┌──────────┐
│ speaking │
└────┬─────┘
     │ completed
     ▼
┌──────────┐
│ cooldown │
└────┬─────┘
     │ cooldown elapsed
     ▼
┌────────────────┐
│ idle_listening │
└────────────────┘

speaking + human speech_start ──▶ interrupted ──▶ cooldown ──▶ idle_listening
```

## Requirements-Gathering Intervention Categories

Erica should have a narrow, useful meeting job: act as a requirements analyst. Initial intervention categories should be explicit and auditable.

| Category | Trigger | Example Erica contribution |
|---|---|---|
| `direct_answer` | Someone addresses Erica by name or asks the bot a clear question. | "Yes. For the initial POC, Google Meet support is in scope; Zoom should remain a follow-up." |
| `clarifying_question` | A requirement has ambiguous actor, scope, rule, or acceptance criteria. | "When you say admin, do you mean internal support admin or tenant admin?" |
| `gap_detection` | A discussed requirement is missing acceptance criteria or operational constraints. | "Do we have a definition of done for that workflow?" |
| `conflict_detection` | Current discussion conflicts with earlier requirement or decision. | "Earlier we said users cannot delete records, but this flow assumes deletion. Which should win?" |
| `decision_capture` | The group appears to have made a decision. | "I heard the decision as: use Google Meet first and defer Zoom. Is that correct?" |
| `scope_control` | The meeting drifts away from the current requirements topic. | "Should I park that as a future enhancement and bring us back to onboarding?" |
| `summary_checkpoint` | A long topic winds down or shifts. | "Quick checkpoint: I have three requirements and two open questions." |

## Conversation Memory Shape

Erica should maintain structured meeting state in addition to recent transcript text.

Candidate model:

```python
@dataclass
class MeetingContext:
    recent_utterances: deque[Utterance]
    participants: dict[str, ParticipantState]
    current_topic: str | None
    requirements: list[RequirementCandidate]
    open_questions: list[OpenQuestion]
    decisions: list[Decision]
    risks: list[Risk]
    parking_lot: list[ParkingLotItem]
    last_agent_speech_at_ms: float | None
    last_human_speech_at_ms: float | None
```

A requirement candidate should eventually track fields such as:

- Actor
- Intent or goal
- System behavior
- Inputs
- Outputs
- Business rule
- Acceptance criteria
- Priority
- Open questions
- Decision owner

Initial code should not overbuild this. Start with recent utterances, candidate interventions, and lightweight requirement/open-question records that can be exposed through an API.

## Policy Direction

Do not let an LLM be the entire state machine.

The deterministic layer should own:

- Current meeting lifecycle state.
- Current participation mode.
- Current runtime state.
- Meeting begin/end transitions and associated setup/teardown.
- Whether TTS is active.
- Cooldowns and minimum silence thresholds.
- Whether Erica was addressed by name.
- Whether STT and TTS are healthy.
- Queue limits and failure behavior.
- Human barge-in interruption behavior.

LLM or classifier logic may own:

- Whether an utterance is a question.
- Whether the question is addressed to Erica.
- Whether a requirement is ambiguous.
- Whether a candidate intervention is useful enough to say.
- Drafting concise meeting-safe language.

This split keeps the system predictable, testable, and debuggable.

## Intervention Scoring

Before speaking, Erica should score candidate actions rather than speaking whenever a plausible response exists.

Candidate scoring dimensions:

| Dimension | Meaning |
|---|---|
| `relevance` | Useful to the current topic. |
| `urgency` | Value may be lost if Erica waits. |
| `confidence` | Erica is likely correct. |
| `interrupt_risk` | Humans may still be in the middle of a thought. |
| `novelty` | The point has not already been made. |
| `mode_allowance` | Current participation mode permits this behavior. |

The policy can start with simple thresholds:

- `passive`: never auto-speak; store candidates silently.
- `assistant`: speak only for direct address/manual trigger.
- `facilitator`: allow high-confidence clarifying questions after a turn boundary and cooldown.

## Proposed Phase 4 Slices

### Phase 4A: Erica State Machine Skeleton

Goal: backend agent consumes finalized transcripts, tracks meeting lifecycle, participation mode, runtime state, and exposes status without auto-speaking.

Likely files:

- `backend/agent/events.py`
- `backend/agent/state.py`
- `backend/agent/orchestrator.py`
- `backend/models/agent.py`
- `backend/main.py`
- `tests/agent/`

Likely endpoints:

- `GET /api/agent`
- `POST /api/agent/mode`
- `POST /api/agent/meeting/begin`
- `POST /api/agent/meeting/end`

### Phase 4B: Direct Question Answering

Goal: Erica speaks only when explicitly addressed.

Initial accepted wake/address patterns:

- "Erica, ..."
- "Hey Erica, ..."
- "Can Erica ..."
- "Ask Erica ..."

State path:

```text
idle_listening → thinking → waiting_for_turn → speaking → cooldown → idle_listening
```

The first implementation may use templated or fake responses so the state machine can be tested without committing to an LLM provider.

### Phase 4C: Silent Requirements Suggestions

Goal: Erica identifies candidate clarifying questions and exposes them through `/api/agent`, but does not speak them automatically unless mode and policy allow it later.

Example payload:

```json
{
  "candidate_interventions": [
    {
      "type": "clarifying_question",
      "text": "Should this approval flow apply to all users or only tenant admins?",
      "score": 0.78,
      "speak_allowed": false,
      "reason": "passive mode stores suggestions silently"
    }
  ]
}
```

### Phase 4D: Facilitator Mode Auto-Speak

Goal: Erica can proactively ask high-value clarifying questions in `facilitator` mode after a safe turn boundary and cooldown.

This should ship only after Phase 4A-4C have good test coverage and observable status.

## Open Questions

1. Should the initial shipped modes be only `off`, `passive`, `assistant`, and `facilitator`?
2. Should direct question answers be templated/fake first, or should Phase 4B immediately wire a real LLM provider?
3. What minimum silence duration should count as Erica's safe turn boundary?
4. Should Erica write structured requirements to a persisted artifact during the meeting, or only keep in-memory state for the first pass?
5. Should the extension expose mode controls immediately, or should mode be backend API-only for the first implementation?

## Consequences

- Erica's active behavior becomes observable before it becomes autonomous.
- Direct-address Q&A provides a safer first active behavior than proactive facilitation.
- Silent candidate interventions create a useful debug path for requirements analysis without meeting disruption.
- The deterministic policy layer makes latency, cooldown, interruption, and mode behavior testable without depending on LLM output.
- A later LangGraph or planner layer can be added behind the policy without replacing the core state machine.
