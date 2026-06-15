import * as React from "react";

import type { AudioDevicesStatus } from "./messages";

interface AudioDevicesSnapshot {
  status?: AudioDevicesStatus;
  error?: string;
  endpointUrl?: string;
}

export function useAudioDevices(backendWsUrl: string, pollMs = 3000): AudioDevicesSnapshot {
  const [snapshot, setSnapshot] = React.useState<AudioDevicesSnapshot>({});

  React.useEffect(() => {
    const endpointUrl = devicesEndpointFromWsUrl(backendWsUrl);
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
          throw new Error(`Audio devices ${response.status}`);
        }
        const status = (await response.json()) as AudioDevicesStatus;
        if (!cancelled) {
          setSnapshot({ endpointUrl: url, status, error: status.error });
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

function devicesEndpointFromWsUrl(backendWsUrl: string): string | undefined {
  try {
    const url = new URL(backendWsUrl);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "/api/audio/devices";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return undefined;
  }
}
