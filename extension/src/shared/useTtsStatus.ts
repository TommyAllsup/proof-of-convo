import * as React from "react";

import type { TtsStatus } from "./messages";

interface TtsSnapshot {
  status?: TtsStatus;
  error?: string;
  endpointUrl?: string;
  speakEndpointUrl?: string;
  interruptEndpointUrl?: string;
  speak: (text: string, interrupt?: boolean) => Promise<void>;
  interrupt: () => Promise<void>;
}

export function useTtsStatus(backendWsUrl: string, pollMs = 1000): TtsSnapshot {
  const [snapshot, setSnapshot] = React.useState<Omit<TtsSnapshot, "speak" | "interrupt">>({});

  React.useEffect(() => {
    const endpointUrl = ttsEndpointFromWsUrl(backendWsUrl);
    if (!endpointUrl) {
      setSnapshot({ error: "Invalid backend URL" });
      return;
    }

    const url = endpointUrl;
    let cancelled = false;

    async function refresh(): Promise<void> {
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`TTS status ${response.status}`);
        }
        const status = (await response.json()) as TtsStatus;
        if (!cancelled) {
          setSnapshot({
            endpointUrl: url,
            speakEndpointUrl: speakEndpointFromStatusUrl(url),
            interruptEndpointUrl: interruptEndpointFromStatusUrl(url),
            status
          });
        }
      } catch (error) {
        if (!cancelled) {
          setSnapshot({
            endpointUrl: url,
            speakEndpointUrl: speakEndpointFromStatusUrl(url),
            interruptEndpointUrl: interruptEndpointFromStatusUrl(url),
            error: error instanceof Error ? error.message : String(error)
          });
        }
      }
    }

    void refresh();
    const intervalId = window.setInterval(() => void refresh(), pollMs);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [backendWsUrl, pollMs]);

  const speak = React.useCallback(
    async (text: string, interrupt = false): Promise<void> => {
      const url = snapshot.speakEndpointUrl ?? speakEndpointFromStatusUrl(ttsEndpointFromWsUrl(backendWsUrl));
      if (!url) {
        throw new Error("Invalid backend URL");
      }
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, interrupt })
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`TTS speak ${response.status}: ${detail}`);
      }
    },
    [backendWsUrl, snapshot.speakEndpointUrl]
  );

  const interrupt = React.useCallback(async (): Promise<void> => {
    const url =
      snapshot.interruptEndpointUrl ?? interruptEndpointFromStatusUrl(ttsEndpointFromWsUrl(backendWsUrl));
    if (!url) {
      throw new Error("Invalid backend URL");
    }
    const response = await fetch(url, { method: "POST" });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`TTS interrupt ${response.status}: ${detail}`);
    }
  }, [backendWsUrl, snapshot.interruptEndpointUrl]);

  return { ...snapshot, speak, interrupt };
}

function ttsEndpointFromWsUrl(backendWsUrl: string): string | undefined {
  try {
    const url = new URL(backendWsUrl);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "/api/tts";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return undefined;
  }
}

function speakEndpointFromStatusUrl(statusUrl: string | undefined): string | undefined {
  if (!statusUrl) {
    return undefined;
  }
  try {
    const url = new URL(statusUrl);
    url.pathname = "/api/tts/speak";
    return url.toString();
  } catch {
    return undefined;
  }
}

function interruptEndpointFromStatusUrl(statusUrl: string | undefined): string | undefined {
  if (!statusUrl) {
    return undefined;
  }
  try {
    const url = new URL(statusUrl);
    url.pathname = "/api/tts/interrupt";
    return url.toString();
  } catch {
    return undefined;
  }
}
