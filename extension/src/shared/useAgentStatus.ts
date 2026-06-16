import * as React from "react";

import type { AgentStatusPayload, ParticipationMode } from "./messages";

interface AgentSnapshot {
  status?: AgentStatusPayload;
  error?: string;
  endpointUrl?: string;
  setMode: (mode: ParticipationMode) => Promise<void>;
  beginMeeting: (meetingUrl?: string) => Promise<void>;
  endMeeting: () => Promise<void>;
  speakCandidate: (candidateId: string) => Promise<void>;
  applyCandidate: (candidateId: string) => Promise<void>;
  dismissCandidate: (candidateId: string) => Promise<void>;
  injectTranscript: (text: string, speaker?: string, sessionId?: string) => Promise<void>;
  setAggressiveness: (aggressiveness: number) => Promise<void>;
  setPolicy: (settings: {
    aggressiveness: number;
    direct_answer_cooldown_ms?: number;
    proactive_min_silence_ms?: number;
  }) => Promise<void>;
  summaryMarkdownUrl?: string;
}

export function useAgentStatus(backendWsUrl: string, pollMs = 1000): AgentSnapshot {
  const [snapshot, setSnapshot] = React.useState<
    Omit<
      AgentSnapshot,
      | "setMode"
      | "beginMeeting"
      | "endMeeting"
      | "speakCandidate"
      | "applyCandidate"
      | "dismissCandidate"
      | "injectTranscript"
      | "setAggressiveness"
      | "setPolicy"
    >
  >({});

  React.useEffect(() => {
    const endpointUrl = agentEndpointFromWsUrl(backendWsUrl);
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
          throw new Error(`Agent status ${response.status}`);
        }
        const status = (await response.json()) as AgentStatusPayload;
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

  const post = React.useCallback(
    async (path: string, body: unknown): Promise<void> => {
      const base = snapshot.endpointUrl ?? agentEndpointFromWsUrl(backendWsUrl);
      if (!base) {
        throw new Error("Invalid backend URL");
      }
      const url = new URL(base);
      url.pathname = path;
      const response = await fetch(url.toString(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`Agent ${path} ${response.status}: ${detail}`);
      }
    },
    [backendWsUrl, snapshot.endpointUrl]
  );

  const setMode = React.useCallback((mode: ParticipationMode) => post("/api/agent/mode", { mode }), [post]);
  const beginMeeting = React.useCallback(
    (meetingUrl?: string) => post("/api/agent/meeting/begin", { meeting_url: meetingUrl ?? null }),
    [post]
  );
  const endMeeting = React.useCallback(() => post("/api/agent/meeting/end", { reason: "manual" }), [post]);
  const speakCandidate = React.useCallback(
    (candidateId: string) => post("/api/agent/candidates/speak", { candidate_id: candidateId, interrupt: true }),
    [post]
  );
  const applyCandidate = React.useCallback(
    (candidateId: string) => post("/api/agent/candidates/apply", { candidate_id: candidateId }),
    [post]
  );
  const dismissCandidate = React.useCallback(
    (candidateId: string) => post("/api/agent/candidates/dismiss", { candidate_id: candidateId }),
    [post]
  );
  const injectTranscript = React.useCallback(
    (text: string, speaker = "Manual", sessionId?: string) =>
      post("/api/agent/transcript", {
        text,
        speaker,
        session_id: sessionId ?? null
      }),
    [post]
  );
  const setAggressiveness = React.useCallback(
    (aggressiveness: number) => post("/api/agent/settings", { aggressiveness }),
    [post]
  );
  const setPolicy = React.useCallback(
    (policy: {
      aggressiveness: number;
      direct_answer_cooldown_ms?: number;
      proactive_min_silence_ms?: number;
    }) => post("/api/agent/settings", policy),
    [post]
  );
  const summaryMarkdownUrl = React.useMemo(() => {
    const base = snapshot.endpointUrl ?? agentEndpointFromWsUrl(backendWsUrl);
    if (!base) {
      return undefined;
    }
    const url = new URL(base);
    url.pathname = "/api/agent/summary.md";
    return url.toString();
  }, [backendWsUrl, snapshot.endpointUrl]);

  return {
    ...snapshot,
    setMode,
    beginMeeting,
    endMeeting,
    speakCandidate,
    applyCandidate,
    dismissCandidate,
    injectTranscript,
    setAggressiveness,
    setPolicy,
    summaryMarkdownUrl
  };
}

function agentEndpointFromWsUrl(backendWsUrl: string): string | undefined {
  try {
    const url = new URL(backendWsUrl);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "/api/agent";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return undefined;
  }
}
