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

export const DEFAULT_SETTINGS: UiSettings = {
  backendWsUrl: "ws://127.0.0.1:8000/ws/audio",
  participationMode: "passive",
  aggressiveness: 25,
  telemetryEnabled: true
};
