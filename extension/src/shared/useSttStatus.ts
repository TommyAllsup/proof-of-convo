import * as React from "react";

import type { SttStatus } from "./messages";

interface SttSnapshot {
  status?: SttStatus;
  error?: string;
  endpointUrl?: string;
}

export function useSttStatus(backendWsUrl: string, pollMs = 1000): SttSnapshot {
  const [snapshot, setSnapshot] = React.useState<SttSnapshot>({});

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

  return snapshot;
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
