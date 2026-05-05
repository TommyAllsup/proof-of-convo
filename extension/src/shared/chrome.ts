export function sendRuntimeMessage<TResponse>(message: unknown): Promise<TResponse> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response: TResponse | undefined) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(response as TResponse);
    });
  });
}

export interface ActiveTab extends chrome.tabs.Tab {
  id: number;
  url: string;
}

export async function queryActiveTab(): Promise<ActiveTab> {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab?.id || !tab.url) {
    throw new Error("No active tab is available.");
  }
  return tab as ActiveTab;
}

export function isMeetUrl(url: string | undefined): boolean {
  if (!url) {
    return false;
  }
  try {
    return new URL(url).hostname === "meet.google.com";
  } catch {
    return false;
  }
}
