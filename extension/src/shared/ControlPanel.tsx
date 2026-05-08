import {
  Activity,
  AudioLines,
  CircleStop,
  Database,
  MessageSquareText,
  Radio,
  PanelRightOpen,
  Play,
  Settings2,
  SlidersHorizontal,
  Waves
} from "lucide-react";
import * as React from "react";

import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader } from "../components/ui/card";
import { Slider } from "../components/ui/slider";
import { sendRuntimeMessage } from "./chrome";
import { startCaptureFromCurrentTab, stopCapture } from "./capture";
import type { ParticipationMode } from "./messages";
import { useAudioConsumerStatus } from "./useAudioConsumerStatus";
import { useRuntimeStatus } from "./useRuntimeStatus";
import { useSettings } from "./useSettings";
import { useSttStatus } from "./useSttStatus";

interface ControlPanelProps {
  surface: "popup" | "sidepanel";
}

const modeLabels: Record<ParticipationMode, string> = {
  passive: "Passive",
  active: "Active",
  qa: "Q&A"
};

export function ControlPanel({ surface }: ControlPanelProps) {
  const status = useRuntimeStatus();
  const { settings, updateSettings } = useSettings();
  const consumer = useAudioConsumerStatus(settings.backendWsUrl);
  const stt = useSttStatus(settings.backendWsUrl);
  const [busy, setBusy] = React.useState(false);
  const [localError, setLocalError] = React.useState<string | undefined>();

  const isStreaming = status.captureState === "streaming";
  const isBusy = busy || status.captureState === "starting" || status.captureState === "stopping";
  const level = Math.min(100, Math.round((status.clientRms ?? status.rms ?? 0) * 420));

  async function runAction(action: () => Promise<unknown>): Promise<void> {
    setBusy(true);
    setLocalError(undefined);
    try {
      await action();
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className={surface === "popup" ? "w-[380px] bg-background p-3" : "min-h-screen bg-background p-4"}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold leading-6 text-foreground">Proof of Conversation</h1>
          <p className="text-xs text-muted-foreground">Google Meet audio capture</p>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-xs">
          <Activity className="h-3.5 w-3.5 text-primary" />
          {status.captureState}
        </div>
      </div>

      <div className="space-y-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium">
              <AudioLines className="h-4 w-4 text-primary" />
              Capture
            </div>
            <div className="text-xs text-muted-foreground">{status.backendState}</div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Latency" value={formatLatency(status.latencyMs)} />
              <Metric label="RMS" value={formatNumber(status.rms ?? status.clientRms)} />
              <Metric label="Dropped" value={String(status.droppedChunks ?? 0)} />
            </div>

            <div className="h-2 overflow-hidden rounded-md bg-muted">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${level}%` }}
                aria-label="Audio level"
              />
            </div>

            <div className="flex gap-2">
              <Button
                className="flex-1"
                disabled={isBusy || isStreaming}
                onClick={() => runAction(startCaptureFromCurrentTab)}
              >
                <Play className="h-4 w-4" />
                Start
              </Button>
              <Button
                className="flex-1"
                variant="danger"
                disabled={isBusy || !isStreaming}
                onClick={() => runAction(stopCapture)}
              >
                <CircleStop className="h-4 w-4" />
                Stop
              </Button>
            </div>

            {surface === "popup" ? (
              <Button
                className="w-full"
                variant="secondary"
                onClick={() => runAction(() => sendRuntimeMessage({ type: "OPEN_SIDE_PANEL" }))}
              >
                <PanelRightOpen className="h-4 w-4" />
                Open Sidebar
              </Button>
            ) : null}

            <StatusLine text={status.meetingUrl ?? "No active Meet session"} />
            <StatusLine text={localError ?? status.error} danger />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium">
              <MessageSquareText className="h-4 w-4 text-primary" />
              Transcript
            </div>
            <div className={stt.status?.stats.running ? "text-xs text-primary" : "text-xs text-muted-foreground"}>
              {stt.status?.stats.running ? "running" : stt.status?.stats.enabled ? "enabled" : "disabled"}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Done" value={formatCount(stt.status?.stats.completed_transcripts)} />
              <Metric label="Queued" value={formatCount(stt.status?.stats.queued_jobs)} />
              <Metric label="Errors" value={formatCount(stt.status?.stats.processing_errors)} />
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <Metric label="STT" value={stt.status?.stats.provider ?? "--"} />
              <Metric label="Speaker" value="heuristic" />
            </div>

            <div className="rounded-md border border-border bg-background">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">Recent utterances</div>
              <div className="max-h-52 overflow-auto">
                {stt.status?.recent_transcripts.length ? (
                  stt.status.recent_transcripts
                    .slice()
                    .reverse()
                    .slice(0, surface === "popup" ? 4 : 10)
                    .map((item) => (
                      <div className="border-b border-border px-3 py-2 last:border-b-0" key={item.utterance.utterance_id}>
                        <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">{item.utterance.speaker}</span>
                          <span>{formatTranscriptTime(item.utterance.start_ms)}</span>
                        </div>
                        <p className="text-xs leading-5 text-foreground">{item.utterance.text || "[empty]"}</p>
                      </div>
                    ))
                ) : (
                  <div className="px-3 py-3 text-xs text-muted-foreground">Waiting for final transcripts</div>
                )}
              </div>
            </div>

            <StatusLine text={stt.error ?? stt.status?.stats.last_error ?? stt.endpointUrl} danger={Boolean(stt.error || stt.status?.stats.last_error)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Radio className="h-4 w-4 text-primary" />
              Consumer
            </div>
            <div className={consumer.status?.stats.running ? "text-xs text-primary" : "text-xs text-muted-foreground"}>
              {consumer.status?.stats.running ? "running" : "offline"}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Consumed" value={formatCount(consumer.status?.stats.consumed_chunks)} />
              <Metric label="Queue" value={formatCount(consumer.status?.stats.queue_depth ?? status.queuedChunks)} />
              <Metric label="Events" value={formatCount(consumer.status?.stats.endpoint_events)} />
            </div>

            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="VAD" value={consumer.status?.stats.vad_provider ?? "--"} />
              <Metric label="Speech p" value={formatNumber(consumer.status?.stats.last_speech_probability ?? undefined)} />
              <Metric label="Last chunk" value={formatRelativeMs(consumer.status?.stats.last_consumed_at_ms)} />
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <Metric label="Errors" value={formatCount(consumer.status?.stats.processing_errors)} />
              <Metric label="VAD errors" value={formatCount(consumer.status?.stats.vad_processing_errors)} />
            </div>

            <div className="rounded-md border border-border bg-background">
              <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-xs font-medium">
                <Waves className="h-3.5 w-3.5 text-primary" />
                Recent endpoints
              </div>
              <div className="max-h-32 overflow-auto">
                {consumer.status?.recent_endpoint_events.length ? (
                  consumer.status.recent_endpoint_events
                    .slice()
                    .reverse()
                    .slice(0, 6)
                    .map((event) => (
                      <div
                        className="grid grid-cols-[88px_1fr_56px] gap-2 border-b border-border px-3 py-2 text-xs last:border-b-0"
                        key={`${event.session_id}-${event.sequence}-${event.type}`}
                      >
                        <span className="font-medium">{event.type.replace("_", " ")}</span>
                        <span className="truncate text-muted-foreground">{event.session_id.slice(0, 8)}</span>
                        <span className="text-right text-muted-foreground">#{event.sequence}</span>
                      </div>
                    ))
                ) : (
                  <div className="px-3 py-3 text-xs text-muted-foreground">Waiting for endpoint events</div>
                )}
              </div>
            </div>

            <StatusLine text={consumer.error ?? consumer.status?.stats.last_error ?? consumer.endpointUrl} danger={Boolean(consumer.error || consumer.status?.stats.last_error)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center gap-2 text-sm font-medium">
            <Settings2 className="h-4 w-4 text-primary" />
            Agent Mode
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-1 rounded-md border border-border bg-muted p-1">
              {(Object.keys(modeLabels) as ParticipationMode[]).map((mode) => (
                <button
                  key={mode}
                  className={
                    settings.participationMode === mode
                      ? "rounded-md bg-white px-2 py-1.5 text-xs font-medium shadow-sm"
                      : "rounded-md px-2 py-1.5 text-xs text-muted-foreground"
                  }
                  onClick={() => updateSettings({ participationMode: mode })}
                >
                  {modeLabels[mode]}
                </button>
              ))}
            </div>

            <label className="block space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  Aggressiveness
                </span>
                <span>{settings.aggressiveness}%</span>
              </div>
              <Slider
                min={0}
                max={100}
                step={5}
                value={settings.aggressiveness}
                onChange={(event) => updateSettings({ aggressiveness: Number(event.currentTarget.value) })}
              />
            </label>

            <label className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2">
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                <Database className="h-3.5 w-3.5 text-primary" />
                Telemetry capture
              </span>
              <input
                className="h-4 w-4 accent-primary"
                type="checkbox"
                checked={settings.telemetryEnabled}
                onChange={(event) => updateSettings({ telemetryEnabled: event.currentTarget.checked })}
              />
            </label>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-background px-2 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="truncate text-sm font-semibold">{value}</div>
    </div>
  );
}

function StatusLine({ text, danger = false }: { text: string | undefined; danger?: boolean }) {
  if (!text) {
    return null;
  }
  return (
    <p className={danger ? "break-words text-xs text-danger" : "break-words text-xs text-muted-foreground"}>
      {text}
    </p>
  );
}

function formatLatency(value: number | undefined): string {
  if (value == null) {
    return "--";
  }
  return `${Math.round(value)} ms`;
}

function formatNumber(value: number | undefined): string {
  if (value == null) {
    return "--";
  }
  return value.toFixed(3);
}

function formatCount(value: number | undefined): string {
  if (value == null) {
    return "--";
  }
  return value.toLocaleString();
}

function formatRelativeMs(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  const ageMs = Date.now() - value;
  if (ageMs < 1500) {
    return "now";
  }
  if (ageMs < 60_000) {
    return `${Math.round(ageMs / 1000)}s ago`;
  }
  return `${Math.round(ageMs / 60_000)}m ago`;
}

function formatTranscriptTime(valueMs: number): string {
  if (valueMs > 1_000_000_000_000) {
    return new Date(valueMs).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    });
  }
  const totalSeconds = Math.max(0, Math.floor(valueMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
