import * as React from "react";

import type { AudioConsumerStatus } from "./messages";

interface AudioConsumerSnapshot {
  status?: AudioConsumerStatus;
  error?: string;
  endpointUrl?: string;
}

export function useAudioConsumerStatus(backendWsUrl: string, pollMs = 1000): AudioConsumerSnapshot {
  const [snapshot, setSnapshot] = React.useState<AudioConsumerSnapshot>({});

  React.useEffect(() => {
    const endpointUrl = consumerEndpointFromWsUrl(backendWsUrl);
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
          throw new Error(`Consumer status ${response.status}`);
        }
        const status = (await response.json()) as AudioConsumerStatus;
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

function consumerEndpointFromWsUrl(backendWsUrl: string): string | undefined {
  try {
    const url = new URL(backendWsUrl);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "/api/audio/consumer";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return undefined;
  }
}
