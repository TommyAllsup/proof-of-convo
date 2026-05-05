import {
  Activity,
  AudioLines,
  CircleStop,
  PanelRightOpen,
  Play,
  Settings2,
  SlidersHorizontal
} from "lucide-react";
import * as React from "react";

import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader } from "../components/ui/card";
import { Slider } from "../components/ui/slider";
import { sendRuntimeMessage } from "./chrome";
import { startCaptureFromCurrentTab, stopCapture } from "./capture";
import type { ParticipationMode } from "./messages";
import { useRuntimeStatus } from "./useRuntimeStatus";
import { useSettings } from "./useSettings";

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

