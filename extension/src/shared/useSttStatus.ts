import * as React from "react";

import type { SttStatus } from "./messages";

interface SttSnapshot {
  status?: SttStatus;
  error?: string;
  endpointUrl?: string;
  setSpeakerLabel: (sessionId: string, speaker: string, label: string | null) => Promise<void>;
}

export function useSttStatus(backendWsUrl: string, pollMs = 1000): SttSnapshot {
  const [snapshot, setSnapshot] = React.useState<Omit<SttSnapshot, "setSpeakerLabel">>({});

  React.useEffect(() => {
    const endpointUrl = sttEndpointFromWsUrl(backendWsUrl);
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
          throw new Error(`STT status ${response.status}`);
        }
        const status = (await response.json()) as SttStatus;
        if (!cancelled) {
          setSnapshot({ endpointUrl: url, status });
        }
      } catch (error) {
        if (!cancelled) {
          setSnapshot({
            endpointUrl: url,
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

  const setSpeakerLabel = React.useCallback(
    async (sessionId: string, speaker: string, label: string | null): Promise<void> => {
      const base = snapshot.endpointUrl ?? sttEndpointFromWsUrl(backendWsUrl);
      if (!base) {
        throw new Error("Invalid backend URL");
      }
      const url = new URL(base);
      url.pathname = "/api/stt/speakers/label";
      const response = await fetch(url.toString(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          speaker,
          label
        })
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`Speaker label ${response.status}: ${detail}`);
      }
    },
    [backendWsUrl, snapshot.endpointUrl]
  );

  return {
    ...snapshot,
    setSpeakerLabel
  };
}

function sttEndpointFromWsUrl(backendWsUrl: string): string | undefined {
  try {
    const url = new URL(backendWsUrl);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "/api/stt";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return undefined;
  }
}
