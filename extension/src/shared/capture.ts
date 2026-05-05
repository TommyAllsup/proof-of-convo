import type { RuntimeStatus } from "./messages";
import { isMeetUrl, queryActiveTab, sendRuntimeMessage } from "./chrome";

export async function startCaptureFromCurrentTab(): Promise<RuntimeStatus> {
  const tab = await queryActiveTab();
  if (!isMeetUrl(tab.url)) {
    throw new Error("Open a meet.google.com tab before starting capture.");
  }

  await sendRuntimeMessage<{ ok: boolean }>({ type: "PREPARE_OFFSCREEN" });
  const streamId = await getMediaStreamId(tab.id);
  return sendRuntimeMessage<RuntimeStatus>({
    type: "START_CAPTURE_WITH_STREAM_ID",
    streamId,
    tabId: tab.id,
    meetingUrl: tab.url
  });
}

export async function stopCapture(): Promise<RuntimeStatus> {
  return sendRuntimeMessage<RuntimeStatus>({ type: "STOP_CAPTURE", reason: "user_stop" });
}

function getMediaStreamId(targetTabId: number): Promise<string> {
  return new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId }, (streamId) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(streamId);
    });
  });
}
