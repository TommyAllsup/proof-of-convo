export type CaptureState = "idle" | "starting" | "streaming" | "stopping" | "error";
export type BackendState = "disconnected" | "connecting" | "connected" | "buffering" | "error";
export type ParticipationMode = "passive" | "active" | "qa";

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
  speaker_confidence: number | null;
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
