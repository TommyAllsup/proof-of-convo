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

export interface UiSettings {
  backendWsUrl: string;
  participationMode: ParticipationMode;
  aggressiveness: number;
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
  aggressiveness: 25
};
