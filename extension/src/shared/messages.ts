export type CaptureState = "idle" | "starting" | "streaming" | "stopping" | "error";
export type BackendState = "disconnected" | "connecting" | "connected" | "buffering" | "error";
export type ParticipationMode = "off" | "passive" | "assistant" | "facilitator" | "qa" | "scribe";
export type MeetingLifecycleState =
  | "not_in_meeting"
  | "joining_meeting"
  | "meeting_started"
  | "in_meeting"
  | "ending_meeting"
  | "meeting_ended";
export type AgentRuntimeState =
  | "idle_listening"
  | "candidate_intervention"
  | "waiting_for_turn"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "cooldown"
  | "manual_override";

export interface RuntimeStatus {
  captureState: CaptureState;
  backendState: BackendState;
  activeTabId?: number;
  meetingUrl?: string;
  sessionId?: string;
  sequence?: number;
  latencyMs?: number;
  rms?: number;
  peak?: number;
  clientRms?: number;
  droppedChunks?: number;
  queuedChunks?: number;
  error?: string;
  updatedAt: number;
}

export interface AudioConsumerStats {
  running: boolean;
  vad_provider: string;
  consumed_chunks: number;
  endpoint_events: number;
  processing_errors: number;
  vad_processing_errors: number;
  last_consumed_at_ms: number | null;
  last_error: string | null;
  queue_depth: number;
  recent_endpoint_events: number;
  last_speech_probability: number | null;
}

export interface AudioConsumerEndpointEvent {
  type: "speech_start" | "speech_end";
  session_id: string;
  sequence: number;
  event_ms: number;
  segment: {
    session_id: string;
    start_ms: number;
    end_ms: number;
    duration_ms: number;
    start_sequence: number;
    end_sequence: number;
    peak: number;
    mean_rms: number;
  } | null;
}

export interface AudioConsumerStatus {
  stats: AudioConsumerStats;
  recent_endpoint_events: AudioConsumerEndpointEvent[];
}

export interface SttWorkerStats {
  enabled: boolean;
  running: boolean;
  provider: string;
  model_id: string;
  diarization_provider?: string;
  model_load_time_s: number | null;
  queued_jobs: number;
  enqueued_jobs: number;
  dropped_jobs: number;
  completed_transcripts: number;
  processing_errors: number;
  last_completed_at_ms: number | null;
  last_error: string | null;
  recent_transcripts: number;
}

export interface UtteranceEvent {
  type: "utterance";
  utterance_id: string;
  session_id: string;
  speaker: string;
  start_ts: number;
  end_ts: number;
  start_ms: number;
  end_ms: number;
  text: string;
  is_final: boolean;
  confidence: number | null;
  speaker_confidence?: number | null;
  speaker_label?: string | null;
  diarization_provider?: string | null;
  speaker_merge_state?: string | null;
  stt_provider: string;
  stt_model: string;
  vad_provider: string;
  raw_audio_ref: string | null;
}

export interface SttTranscriptItem {
  completed_at_ms: number;
  utterance: UtteranceEvent;
  speaker: {
    speaker: string;
    confidence: number;
    method: string;
    provider?: string;
    merge_state?: string;
    speaker_label?: string | null;
  };
  transcript: {
    window_id: string;
    provider: string;
    model_id: string;
    text: string;
    language: string | null;
    confidence: number | null;
    wall_time_s: number;
    error: string | null;
  };
}

export interface SttStatus {
  stats: SttWorkerStats;
  recent_transcripts: SttTranscriptItem[];
}

export interface TtsWorkerStats {
  enabled: boolean;
  running: boolean;
  provider: string;
  model_id: string;
  voice_id: string;
  voice_name: string;
  sample_rate: number;
  player: string;
  output_device: string | null;
  playback_enabled: boolean;
  queued_jobs: number;
  enqueued_jobs: number;
  dropped_jobs: number;
  completed_speeches: number;
  processing_errors: number;
  total_audio_bytes: number;
  interrupted_speeches: number;
  active_job_id: string | null;
  last_started_at_ms: number | null;
  last_completed_at_ms: number | null;
  last_ttfa_ms: number | null;
  last_error: string | null;
  recent_speeches: number;
}

export interface TtsSpeechItem {
  job_id: string;
  text: string;
  provider: string;
  model_id: string;
  voice_id: string;
  voice_name: string;
  queued_at_ms: number;
  started_at_ms: number;
  completed_at_ms: number;
  ttfa_ms: number | null;
  wall_time_s: number;
  audio_bytes: number;
  sample_rate: number;
  dump_path: string | null;
  error: string | null;
  interrupted: boolean;
  interrupt_reason: string | null;
}

export interface TtsStatus {
  stats: TtsWorkerStats;
  recent_speeches: TtsSpeechItem[];
}

export interface AudioOutputDevice {
  index: number;
  name: string;
  max_output_channels: number;
  default_samplerate: number;
}

export interface AudioDevicesStatus {
  ok: boolean;
  error?: string;
  output_devices: AudioOutputDevice[];
}

export interface AgentUtterance {
  utterance_id: string;
  session_id: string;
  speaker: string;
  text: string;
  start_ms: number;
  end_ms: number;
  received_at_ms: number;
}

export interface ParticipantState {
  speaker: string;
  utterance_count: number;
  last_heard_at_ms: number | null;
}

export interface AgentCandidateIntervention {
  candidate_id: string;
  type:
    | "direct_answer"
    | "clarifying_question"
    | "gap_detection"
    | "conflict_detection"
    | "decision_capture"
    | "scope_control"
    | "summary_checkpoint"
    | "mode_change";
  text: string;
  score: number;
  speak_allowed: boolean;
  reason: string;
  source_utterance_id: string | null;
  suggested_mode: ParticipationMode | null;
  created_at_ms: number;
}

export interface AgentReasoningTrace {
  trace_id: string;
  utterance_id: string;
  action:
    | "listen"
    | "draft_candidate"
    | "speak_now"
    | "summarize"
    | "capture_decision"
    | "ask_clarifying_question"
    | "suggest_mode_change"
    | null;
  candidate_type: AgentCandidateIntervention["type"] | null;
  score: number | null;
  reason: string | null;
  suggested_mode: ParticipationMode | null;
  error: string | null;
  created_at_ms: number;
  mode: ParticipationMode;
  runtime_state: AgentRuntimeState;
  can_auto_speak: boolean;
  cooldown_allows_speech: boolean;
  context_summary_count: number;
  recent_utterance_count: number;
}

export interface AgentLLMCallTrace {
  trace_id: string;
  operation: "reasoning" | "direct_answer" | "context_summary";
  provider: string;
  success: boolean;
  latency_ms: number;
  error: string | null;
  input_preview: string | null;
  output_preview: string | null;
  created_at_ms: number;
}

export interface RequirementRecord {
  requirement_id: string;
  text: string;
  source_utterance_id: string;
  source_utterance_ids: string[];
  speaker: string;
  created_at_ms: number;
  actor: string | null;
  goal: string | null;
  behavior: string | null;
  constraints: string[];
  priority: "unknown" | "low" | "medium" | "high";
  owner: string | null;
  status: "proposed" | "clarifying" | "accepted" | "deferred";
  acceptance_criteria: string[];
  open_questions: string[];
}

export interface OpenQuestionRecord {
  question_id: string;
  text: string;
  source_utterance_id: string;
  source_utterance_ids: string[];
  speaker: string;
  created_at_ms: number;
  answered: boolean;
  related_requirement_ids: string[];
}

export interface DecisionRecord {
  decision_id: string;
  text: string;
  source_utterance_id: string;
  source_utterance_ids: string[];
  speaker: string;
  created_at_ms: number;
  confirmed: boolean;
}

export interface ActionItemRecord {
  action_item_id: string;
  text: string;
  source_utterance_id: string;
  source_utterance_ids: string[];
  speaker: string;
  created_at_ms: number;
  owner: string | null;
  completed: boolean;
}

export interface RiskRecord {
  risk_id: string;
  text: string;
  source_utterance_id: string;
  source_utterance_ids: string[];
  speaker: string;
  created_at_ms: number;
  severity: string;
  mitigated: boolean;
}

export interface ParkedTopicRecord {
  parked_topic_id: string;
  text: string;
  source_utterance_id: string;
  source_utterance_ids: string[];
  speaker: string;
  created_at_ms: number;
  revisited: boolean;
}

export interface MeetingContextSummary {
  summary_id: string;
  start_utterance_id: string;
  end_utterance_id: string;
  generated_at_ms: number;
  utterance_count: number;
  text: string;
  topics: string[];
}

export interface CurrentTopicState {
  topic: string;
  source_utterance_id: string;
  updated_at_ms: number;
}

export interface MeetingSummaryArtifact {
  meeting_id: string | null;
  meeting_url: string | null;
  generated_at_ms: number;
  utterance_count: number;
  participant_count: number;
  requirements: RequirementRecord[];
  open_questions: OpenQuestionRecord[];
  decisions: DecisionRecord[];
  action_items: ActionItemRecord[];
  risks: RiskRecord[];
  parked_topics: ParkedTopicRecord[];
  context_summaries: MeetingContextSummary[];
  current_topic: CurrentTopicState | null;
  candidate_interventions: AgentCandidateIntervention[];
  markdown: string;
  json_path: string | null;
  markdown_path: string | null;
}

export interface AgentStatusPayload {
  status: {
    name: string;
    mode: ParticipationMode;
    lifecycle_state: MeetingLifecycleState;
    runtime_state: AgentRuntimeState;
    meeting_id: string | null;
    meeting_url: string | null;
    recent_utterances: AgentUtterance[];
    participants: ParticipantState[];
    requirements: RequirementRecord[];
    open_questions: OpenQuestionRecord[];
    decisions: DecisionRecord[];
    action_items: ActionItemRecord[];
    risks: RiskRecord[];
    parked_topics: ParkedTopicRecord[];
    context_summaries: MeetingContextSummary[];
    current_topic: CurrentTopicState | null;
  candidate_interventions: AgentCandidateIntervention[];
  reasoning_traces: AgentReasoningTrace[];
  llm_call_traces: AgentLLMCallTrace[];
  latest_summary: MeetingSummaryArtifact | null;
    settings: {
      aggressiveness: number;
      direct_answer_cooldown_ms: number;
      proactive_min_silence_ms: number;
    };
    readiness: {
      can_auto_speak: boolean;
      blockers: string[];
    };
    active_speech_job_id: string | null;
    last_speech_job_id: string | null;
    last_agent_speech_at_ms: number | null;
    last_human_speech_at_ms: number | null;
    last_state_change_at_ms: number;
    last_error: string | null;
  };
}

export interface UiSettings {
  backendWsUrl: string;
  participationMode: ParticipationMode;
  aggressiveness: number;
  telemetryEnabled: boolean;
}

export interface StartCaptureWithStreamIdRequest {
  type: "START_CAPTURE_WITH_STREAM_ID";
  streamId: string;
  tabId: number;
  meetingUrl: string;
}

export interface StopCaptureRequest {
  type: "STOP_CAPTURE";
  reason?: string;
}

export interface GetStatusRequest {
  type: "GET_STATUS";
}

export interface GetSettingsRequest {
  type: "GET_SETTINGS";
}

export interface SaveSettingsRequest {
  type: "SAVE_SETTINGS";
  settings: Partial<UiSettings>;
}

export interface OpenSidePanelRequest {
  type: "OPEN_SIDE_PANEL";
}

export interface PrepareOffscreenRequest {
  type: "PREPARE_OFFSCREEN";
}

export interface StartOffscreenCaptureRequest {
  target: "offscreen";
  type: "START_OFFSCREEN_CAPTURE";
  streamId: string;
  sessionId: string;
  tabId: number;
  meetingUrl: string;
  backendWsUrl: string;
  telemetryEnabled: boolean;
}

export interface StopOffscreenCaptureRequest {
  target: "offscreen";
  type: "STOP_OFFSCREEN_CAPTURE";
  reason?: string;
}

export interface StartContentMicCaptureRequest {
  target: "content";
  type: "START_CONTENT_MIC_CAPTURE";
  sessionId: string;
  tabId: number;
  meetingUrl: string;
  backendWsUrl: string;
  telemetryEnabled: boolean;
}

export interface StopContentMicCaptureRequest {
  target: "content";
  type: "STOP_CONTENT_MIC_CAPTURE";
  reason?: string;
}

export interface OffscreenStatusMessage {
  type: "OFFSCREEN_STATUS";
  status: Partial<RuntimeStatus>;
}

export interface StatusUpdateMessage {
  type: "STATUS_UPDATE";
  status: RuntimeStatus;
}

export type RuntimeRequest =
  | StartCaptureWithStreamIdRequest
  | StopCaptureRequest
  | GetStatusRequest
  | GetSettingsRequest
  | SaveSettingsRequest
  | OpenSidePanelRequest
  | PrepareOffscreenRequest
  | OffscreenStatusMessage;

export type ContentCaptureRequest = StartContentMicCaptureRequest | StopContentMicCaptureRequest;

export const DEFAULT_SETTINGS: UiSettings = {
  backendWsUrl: "ws://127.0.0.1:8000/ws/audio",
  participationMode: "passive",
  aggressiveness: 25,
  telemetryEnabled: true
};
