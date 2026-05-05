import type { StatusUpdateMessage } from "./shared/messages";

const BADGE_ID = "proof-of-convo-status-badge";

function ensureBadge(): HTMLDivElement {
  const existing = document.getElementById(BADGE_ID);
  if (existing instanceof HTMLDivElement) {
    return existing;
  }

  const badge = document.createElement("div");
  badge.id = BADGE_ID;
  badge.style.position = "fixed";
  badge.style.right = "16px";
  badge.style.bottom = "16px";
  badge.style.zIndex = "2147483647";
  badge.style.borderRadius = "8px";
  badge.style.padding = "8px 10px";
  badge.style.background = "rgba(15, 23, 42, 0.88)";
  badge.style.color = "white";
  badge.style.font = "12px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
  badge.style.boxShadow = "0 8px 24px rgba(0,0,0,0.22)";
  badge.style.pointerEvents = "none";
  badge.textContent = "Agent idle";
  document.documentElement.appendChild(badge);
  return badge;
}

function setBadgeText(text: string, active: boolean): void {
  const badge = ensureBadge();
  badge.textContent = text;
  badge.style.background = active ? "rgba(15, 118, 110, 0.92)" : "rgba(15, 23, 42, 0.88)";
}

chrome.runtime.onMessage.addListener((message: StatusUpdateMessage) => {
  if (message.type !== "STATUS_UPDATE") {
    return;
  }

  const { captureState, backendState, latencyMs } = message.status;
  if (captureState === "streaming") {
    const latency = latencyMs == null ? "" : ` ${Math.round(latencyMs)}ms`;
    setBadgeText(`Agent listening${latency}`, true);
    return;
  }

  if (captureState === "error") {
    setBadgeText("Agent error", false);
    return;
  }

  setBadgeText(backendState === "connecting" ? "Agent connecting" : "Agent idle", false);
});

