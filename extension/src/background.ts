import {
  DEFAULT_SETTINGS,
  type RuntimeRequest,
  type RuntimeStatus,
  type StatusUpdateMessage,
  type UiSettings
} from "./shared/messages";

const OFFSCREEN_DOCUMENT_PATH = "offscreen.html";
const STORAGE_SETTINGS_KEY = "proof.settings";
const STORAGE_STATUS_KEY = "proof.status";

let status: RuntimeStatus = {
  captureState: "idle",
  backendState: "disconnected",
  updatedAt: Date.now()
};

let settings: UiSettings = { ...DEFAULT_SETTINGS };

async function loadSettings(): Promise<UiSettings> {
  const stored = await chrome.storage.local.get(STORAGE_SETTINGS_KEY);
  settings = { ...DEFAULT_SETTINGS, ...(stored[STORAGE_SETTINGS_KEY] ?? {}) };
  return settings;
}

async function saveSettings(update: Partial<UiSettings>): Promise<UiSettings> {
  settings = { ...settings, ...update };
  await chrome.storage.local.set({ [STORAGE_SETTINGS_KEY]: settings });
  return settings;
}

async function loadStatus(): Promise<RuntimeStatus> {
  const stored = await chrome.storage.session.get(STORAGE_STATUS_KEY);
  status = { ...status, ...(stored[STORAGE_STATUS_KEY] ?? {}) };
  return status;
}

async function broadcastStatus(update: Partial<RuntimeStatus>): Promise<RuntimeStatus> {
  status = {
    ...status,
    ...update,
    updatedAt: Date.now()
  };
  await chrome.storage.session.set({ [STORAGE_STATUS_KEY]: status });

  if (status.activeTabId !== undefined) {
    await updateActionForTab(status.activeTabId);
  }

  const message: StatusUpdateMessage = { type: "STATUS_UPDATE", status };
  chrome.runtime.sendMessage(message).catch(() => undefined);
  return status;
}

async function hasOffscreenDocument(): Promise<boolean> {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT],
    documentUrls: [chrome.runtime.getURL(OFFSCREEN_DOCUMENT_PATH)]
  });
  return contexts.length > 0;
}

async function ensureOffscreenDocument(): Promise<void> {
  if (await hasOffscreenDocument()) {
    return;
  }

  await chrome.offscreen.createDocument({
    url: OFFSCREEN_DOCUMENT_PATH,
    reasons: [chrome.offscreen.Reason.USER_MEDIA],
    justification: "Capture Google Meet tab audio with Web Audio outside the MV3 service worker."
  });
}

async function closeOffscreenDocumentIfIdle(): Promise<void> {
  if (status.captureState === "idle" && (await hasOffscreenDocument())) {
    await chrome.offscreen.closeDocument();
  }
}

async function startCaptureFromStreamId(
  streamId: string,
  tabId: number,
  meetingUrl: string
): Promise<RuntimeStatus> {
  await loadSettings();
  await ensureOffscreenDocument();

  const sessionId = crypto.randomUUID();
  await broadcastStatus({
    captureState: "starting",
    backendState: "connecting",
    activeTabId: tabId,
    meetingUrl,
    sessionId,
    sequence: 0,
    latencyMs: undefined,
    rms: 0,
    peak: 0,
    droppedChunks: 0,
    queuedChunks: 0,
    error: undefined
  });

  await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "START_OFFSCREEN_CAPTURE",
    streamId,
    sessionId,
    tabId,
    meetingUrl,
    backendWsUrl: settings.backendWsUrl,
    telemetryEnabled: settings.telemetryEnabled
  });

  return status;
}

async function stopCapture(reason = "user_stop"): Promise<RuntimeStatus> {
  await broadcastStatus({ captureState: "stopping" });
  chrome.runtime
    .sendMessage({ target: "offscreen", type: "STOP_OFFSCREEN_CAPTURE", reason })
    .catch(() => undefined);
  if (status.activeTabId !== undefined) {
    chrome.tabs
      .sendMessage(status.activeTabId, { target: "content", type: "STOP_CONTENT_MIC_CAPTURE", reason })
      .catch(() => undefined);
  }
  await broadcastStatus({
    captureState: "idle",
    backendState: "disconnected",
    activeTabId: undefined,
    sessionId: undefined,
    error: undefined
  });
  await closeOffscreenDocumentIfIdle();
  return status;
}

async function openSidePanel(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) {
    await chrome.sidePanel.open({ tabId: tab.id });
  }
}

async function updateActionForTab(tabId: number): Promise<void> {
  const tab = await chrome.tabs.get(tabId).catch(() => undefined);
  const isMeet = isMeetUrl(tab?.url);
  const isActiveCapture = status.activeTabId === tabId && status.captureState === "streaming";

  await chrome.action.setBadgeText({ tabId, text: isActiveCapture ? "ON" : isMeet ? "Meet" : "" });
  await chrome.action.setBadgeBackgroundColor({
    tabId,
    color: isActiveCapture ? "#0f766e" : "#64748b"
  });

  if (chrome.sidePanel) {
    await chrome.sidePanel.setOptions({
      tabId,
      path: "sidepanel.html",
      enabled: isMeet
    });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  loadSettings().catch(console.error);
  chrome.storage.session.set({ [STORAGE_STATUS_KEY]: status }).catch(console.error);
});

chrome.runtime.onStartup.addListener(() => {
  loadSettings().catch(console.error);
  loadStatus().catch(console.error);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status || changeInfo.url) {
    updateActionForTab(tabId).catch(console.error);
  }

  if (status.activeTabId === tabId && tab.url && !isMeetUrl(tab.url)) {
    stopCapture("tab_navigated_away").catch(console.error);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (status.activeTabId === tabId) {
    stopCapture("tab_closed").catch(console.error);
  }
});

chrome.tabCapture.onStatusChanged.addListener((info) => {
  if (info.tabId === status.activeTabId && info.status === "stopped") {
    stopCapture("tab_capture_stopped").catch(console.error);
  }
});

chrome.runtime.onMessage.addListener((message: RuntimeRequest, _sender, sendResponse) => {
  void (async () => {
    switch (message.type) {
      case "PREPARE_OFFSCREEN":
        await ensureOffscreenDocument();
        sendResponse({ ok: true });
        break;
      case "START_CAPTURE_WITH_STREAM_ID":
        sendResponse(
          await startCaptureFromStreamId(message.streamId, message.tabId, message.meetingUrl)
        );
        break;
      case "STOP_CAPTURE":
        sendResponse(await stopCapture(message.reason));
        break;
      case "GET_STATUS":
        sendResponse(await loadStatus());
        break;
      case "GET_SETTINGS":
        sendResponse(await loadSettings());
        break;
      case "SAVE_SETTINGS":
        sendResponse(await saveSettings(message.settings));
        break;
      case "OPEN_SIDE_PANEL":
        await openSidePanel();
        sendResponse({ ok: true });
        break;
      case "OFFSCREEN_STATUS":
        sendResponse(await broadcastStatus(message.status));
        break;
      default:
        sendResponse({ error: "unknown message type" });
    }
  })().catch(async (error: unknown) => {
    const messageText = error instanceof Error ? error.message : String(error);
    const nextStatus = await broadcastStatus({
      captureState: "error",
      backendState: "error",
      error: messageText
    });
    sendResponse(nextStatus);
  });

  return true;
});

function isMeetUrl(url: string | undefined): boolean {
  if (!url) {
    return false;
  }
  try {
    return new URL(url).hostname === "meet.google.com";
  } catch {
    return false;
  }
}
