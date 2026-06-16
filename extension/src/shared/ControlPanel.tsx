import {
  Activity,
  AudioLines,
  Bot,
  Check,
  CircleStop,
  Database,
  MessageSquareText,
  Radio,
  PanelRightOpen,
  Play,
  SlidersHorizontal,
  Volume2,
  VolumeX,
  Waves,
  X
} from "lucide-react";
import * as React from "react";

import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader } from "../components/ui/card";
import { Slider } from "../components/ui/slider";
import { sendRuntimeMessage } from "./chrome";
import { startCaptureFromCurrentTab, stopCapture } from "./capture";
import type {
  AgentStatusPayload,
  AgentLLMCallTrace,
  AgentReasoningTrace,
  ParticipationMode,
  RequirementRecord
} from "./messages";
import { useAgentStatus } from "./useAgentStatus";
import { useAudioConsumerStatus } from "./useAudioConsumerStatus";
import { useAudioDevices } from "./useAudioDevices";
import { useRuntimeStatus } from "./useRuntimeStatus";
import { useSettings } from "./useSettings";
import { useSttStatus } from "./useSttStatus";
import { useTtsStatus } from "./useTtsStatus";

interface ControlPanelProps {
  surface: "popup" | "sidepanel";
}

const modeLabels: Record<ParticipationMode, string> = {
  off: "Off",
  passive: "Passive",
  assistant: "Assistant",
  facilitator: "Facilitator",
  qa: "Q&A",
  scribe: "Scribe"
};

export function ControlPanel({ surface }: ControlPanelProps) {
  const status = useRuntimeStatus();
  const { settings, updateSettings } = useSettings();
  const consumer = useAudioConsumerStatus(settings.backendWsUrl);
  const devices = useAudioDevices(settings.backendWsUrl);
  const stt = useSttStatus(settings.backendWsUrl);
  const tts = useTtsStatus(settings.backendWsUrl);
  const agent = useAgentStatus(settings.backendWsUrl);
  const [busy, setBusy] = React.useState(false);
  const [localError, setLocalError] = React.useState<string | undefined>();
  const [speakText, setSpeakText] = React.useState("Thanks. I have one clarifying question: what decision do we need before the next step?");
  const [manualSpeaker, setManualSpeaker] = React.useState("Manual");
  const [manualUtterance, setManualUtterance] = React.useState("Erica, what requirements are still unclear?");
  const [speakerLabelDrafts, setSpeakerLabelDrafts] = React.useState<Record<string, string>>({});

  const isStreaming = status.captureState === "streaming";
  const isBusy = busy || status.captureState === "starting" || status.captureState === "stopping";
  const level = Math.min(100, Math.round((status.clientRms ?? status.rms ?? 0) * 420));
  const outputDevice = tts.status?.stats.output_device;
  const outputVisible = isOutputDeviceVisible(devices.status, outputDevice);
  const agentStatus = normalizeAgentStatus(agent.status);
  const recentTranscripts = stt.status?.recent_transcripts ?? [];
  const recentEndpointEvents = consumer.status?.recent_endpoint_events ?? [];

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
              <Metric label="Speaker" value={stt.status?.stats.diarization_provider ?? "--"} />
            </div>

            <div className="rounded-md border border-border bg-background">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">Recent utterances</div>
              <div className="max-h-52 overflow-auto">
                {recentTranscripts.length ? (
                  recentTranscripts
                    .slice()
                    .reverse()
                    .slice(0, surface === "popup" ? 4 : 10)
                    .map((item) => {
                      const speakerLabel = item.utterance.speaker_label ?? item.speaker.speaker_label ?? null;
                      const speakerName = speakerLabel ?? item.utterance.speaker ?? item.speaker.speaker ?? "Speaker";
                      const labelKey = `${item.utterance.session_id ?? "session"}:${item.utterance.speaker ?? item.speaker.speaker ?? "speaker"}`;
                      const labelDraft = speakerLabelDrafts[labelKey] ?? speakerLabel ?? "";
                      return (
                        <div className="border-b border-border px-3 py-2 last:border-b-0" key={item.utterance.utterance_id}>
                          <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                            <span className="min-w-0 truncate font-medium text-foreground" title={item.utterance.speaker}>
                              {speakerName}
                            </span>
                            <span>{formatTranscriptTime(item.utterance.start_ms)}</span>
                          </div>
                          <div className="mb-1 text-[10px] text-muted-foreground">
                            {[
                              item.speaker.provider ?? item.speaker.method ?? "speaker",
                              item.speaker.merge_state ?? "unmerged",
                              formatConfidence(item.speaker.confidence)
                            ].join(" / ")}
                          </div>
                          {surface === "sidepanel" ? (
                            <div className="mb-2 flex gap-1">
                              <input
                                className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] outline-none focus:border-primary"
                                value={labelDraft}
                                onChange={(event) =>
                                  setSpeakerLabelDrafts((drafts) => ({
                                    ...drafts,
                                    [labelKey]: event.currentTarget.value
                                  }))
                                }
                                placeholder={item.utterance.speaker}
                              />
                              <Button
                                aria-label="Save speaker label"
                                className="h-7 w-7 px-0"
                                disabled={isBusy}
                                onClick={() =>
                                  runAction(() =>
                                    stt.setSpeakerLabel(
                                      item.utterance.session_id,
                                      item.utterance.speaker ?? item.speaker.speaker,
                                      labelDraft.trim() || null
                                    )
                                  )
                                }
                              >
                                <Check className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                aria-label="Clear speaker label"
                                className="h-7 w-7 px-0"
                                variant="secondary"
                                disabled={isBusy || !speakerLabel}
                                onClick={() =>
                                  runAction(async () => {
                                    await stt.setSpeakerLabel(
                                      item.utterance.session_id,
                                      item.utterance.speaker ?? item.speaker.speaker,
                                      null
                                    );
                                    setSpeakerLabelDrafts((drafts) => ({
                                      ...drafts,
                                      [labelKey]: ""
                                    }));
                                  })
                                }
                              >
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          ) : null}
                          <p className="text-xs leading-5 text-foreground">{item.utterance.text || "[empty]"}</p>
                        </div>
                      );
                    })
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
              <Volume2 className="h-4 w-4 text-primary" />
              Voice
            </div>
            <div className={tts.status?.stats.running ? "text-xs text-primary" : "text-xs text-muted-foreground"}>
              {tts.status?.stats.running ? "running" : tts.status?.stats.enabled ? "enabled" : "disabled"}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Spoken" value={formatCount(tts.status?.stats.completed_speeches)} />
              <Metric label="Queue" value={formatCount(tts.status?.stats.queued_jobs)} />
              <Metric label="TTFA" value={formatLatency(tts.status?.stats.last_ttfa_ms ?? undefined)} />
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <Metric label="TTS" value={tts.status?.stats.provider ?? "--"} />
              <Metric label="Output" value={tts.status?.stats.output_device ?? tts.status?.stats.player ?? "--"} />
            </div>

            {tts.status?.stats.playback_enabled ? (
              <StatusLine
                text={
                  outputVisible
                    ? `Output device visible: ${outputDevice}`
                    : `Output device not visible: ${outputDevice ?? "default"}`
                }
                danger={!outputVisible}
              />
            ) : null}

            <label className="block space-y-2">
              <span className="text-xs text-muted-foreground">Manual speak</span>
              <textarea
                className="min-h-20 w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-xs leading-5 outline-none focus:border-primary"
                value={speakText}
                onChange={(event) => setSpeakText(event.currentTarget.value)}
              />
            </label>

            <div className="grid grid-cols-2 gap-2">
              <Button
                disabled={isBusy || !speakText.trim() || !tts.status?.stats.running}
                onClick={() => runAction(() => tts.speak(speakText.trim(), true))}
              >
                <Volume2 className="h-4 w-4" />
                Speak
              </Button>
              <Button
                variant="danger"
                disabled={isBusy || !tts.status?.stats.running}
                onClick={() => runAction(tts.interrupt)}
              >
                <VolumeX className="h-4 w-4" />
                Stop
              </Button>
            </div>

            <StatusLine text={devices.error} danger />
            <StatusLine text={tts.error ?? tts.status?.stats.last_error ?? tts.endpointUrl} danger={Boolean(tts.error || tts.status?.stats.last_error)} />
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
                {recentEndpointEvents.length ? (
                  recentEndpointEvents
                    .slice()
                    .reverse()
                    .slice(0, 6)
                    .map((event) => (
                      <div
                        className="grid grid-cols-[88px_1fr_56px] gap-2 border-b border-border px-3 py-2 text-xs last:border-b-0"
                        key={`${event.session_id}-${event.sequence}-${event.type}`}
                      >
                        <span className="font-medium">{event.type.replace("_", " ")}</span>
                        <span className="truncate text-muted-foreground">{(event.session_id ?? "session").slice(0, 8)}</span>
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
            <Bot className="h-4 w-4 text-primary" />
            Erica
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Lifecycle" value={formatState(agent.status?.status.lifecycle_state)} />
              <Metric label="Runtime" value={formatState(agent.status?.status.runtime_state)} />
              <Metric
                label="Auto speak"
                value={agentStatus.readiness.can_auto_speak ? "ready" : "blocked"}
              />
            </div>

            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Candidates" value={formatCount(agentStatus.candidate_interventions.length)} />
              <Metric label="Reqs" value={formatCount(agentStatus.requirements.length)} />
              <Metric label="Questions" value={formatCount(agentStatus.open_questions.length)} />
            </div>

            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Decisions" value={formatCount(agentStatus.decisions.length)} />
              <Metric label="Actions" value={formatCount(agentStatus.action_items.length)} />
              <Metric label="Risks" value={formatCount(agentStatus.risks.length)} />
            </div>

            <div className="grid grid-cols-3 gap-2 text-xs">
              <Metric label="Parked" value={formatCount(agentStatus.parked_topics.length)} />
              <Metric label="Topic" value={agentStatus.current_topic?.topic ?? "--"} />
              <Metric
                label="Summary"
                value={agentStatus.latest_summary ? "ready" : "not ready"}
              />
            </div>

            <div className="grid grid-cols-3 gap-1 rounded-md border border-border bg-muted p-1">
              {(["off", "passive", "assistant", "facilitator", "qa", "scribe"] as ParticipationMode[]).map((mode) => (
                <button
                  key={mode}
                  className={
                    agent.status?.status.mode === mode
                      ? "rounded-md bg-white px-2 py-1.5 text-xs font-medium shadow-sm"
                      : "rounded-md px-2 py-1.5 text-xs text-muted-foreground"
                  }
                  onClick={() => runAction(() => agent.setMode(mode))}
                >
                  {modeLabels[mode]}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Button
                disabled={isBusy || agentStatus.lifecycle_state === "in_meeting"}
                onClick={() => runAction(() => agent.beginMeeting(status.meetingUrl))}
              >
                <Play className="h-4 w-4" />
                Begin
              </Button>
              <Button
                variant="danger"
                disabled={isBusy || agentStatus.lifecycle_state !== "in_meeting"}
                onClick={() => runAction(agent.endMeeting)}
              >
                <CircleStop className="h-4 w-4" />
                End
              </Button>
            </div>

            <div className="space-y-2 rounded-md border border-border bg-background p-3">
              <div className="flex items-center gap-2 text-xs font-medium">
                <MessageSquareText className="h-3.5 w-3.5 text-primary" />
                Manual utterance
              </div>
              <input
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs outline-none focus:border-primary"
                value={manualSpeaker}
                onChange={(event) => setManualSpeaker(event.currentTarget.value)}
                placeholder="Speaker"
              />
              <textarea
                className="min-h-20 w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-xs leading-5 outline-none focus:border-primary"
                value={manualUtterance}
                onChange={(event) => setManualUtterance(event.currentTarget.value)}
                placeholder="Type a finalized utterance for Erica to observe"
              />
              <Button
                className="w-full"
                variant="secondary"
                disabled={isBusy || !manualUtterance.trim()}
                onClick={() =>
                  runAction(() =>
                    agent.injectTranscript(
                      manualUtterance.trim(),
                      manualSpeaker.trim() || "Manual",
                      status.sessionId
                    )
                  )
                }
              >
                <MessageSquareText className="h-4 w-4" />
                Inject
              </Button>
            </div>

            {agentStatus.latest_summary ? (
              <a
                className="block rounded-md border border-border bg-background px-3 py-2 text-xs font-medium text-primary"
                href={agent.summaryMarkdownUrl}
                rel="noreferrer"
                target="_blank"
              >
                Open meeting summary
              </a>
            ) : null}

            <div className="rounded-md border border-border bg-background">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">Requirements</div>
              <div className="max-h-44 overflow-auto">
                {agentStatus.requirements.length ? (
                  agentStatus.requirements
                    .slice()
                    .reverse()
                    .slice(0, surface === "popup" ? 2 : 6)
                    .map((requirement) => (
                      <div className="space-y-1 border-b border-border px-3 py-2 last:border-b-0" key={requirement.requirement_id}>
                        <p className="text-xs leading-5 text-foreground">{requirement.text}</p>
                        <p className="text-[11px] leading-4 text-muted-foreground">
                          {formatRequirementDetails(requirement)}
                        </p>
                      </div>
                    ))
                ) : (
                  <div className="px-3 py-3 text-xs text-muted-foreground">No requirements yet</div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3">
              <CompactRecordList
                emptyText="No open questions yet"
                items={agentStatus.open_questions.map(formatOpenQuestion)}
                title="Open questions"
              />
              <CompactRecordList
                emptyText="No decisions yet"
                items={agentStatus.decisions.map(formatDecision)}
                title="Decisions"
              />
              <CompactRecordList
                emptyText="No action items yet"
                items={agentStatus.action_items.map(formatActionItem)}
                title="Action items"
              />
            </div>

            <div className="rounded-md border border-border bg-background">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">Candidate interventions</div>
              <div className="max-h-40 overflow-auto">
                {agentStatus.candidate_interventions.length ? (
                  agentStatus.candidate_interventions
                    .slice()
                    .reverse()
                    .slice(0, surface === "popup" ? 2 : 5)
                    .map((candidate) => (
                      <div className="space-y-2 border-b border-border px-3 py-2 last:border-b-0" key={candidate.candidate_id}>
                        <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">{candidate.type.replace("_", " ")}</span>
                          <span>
                            {candidate.suggested_mode ? `${modeLabels[candidate.suggested_mode]} · ` : ""}
                            {Math.round(candidate.score * 100)}%
                          </span>
                        </div>
                        <p className="text-xs leading-5 text-foreground">{candidate.text}</p>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] text-muted-foreground">{candidate.reason}</span>
                          <div className="flex gap-1">
                            {candidate.type === "mode_change" ? (
                              <Button
                                disabled={isBusy || !candidate.suggested_mode}
                                onClick={() => runAction(() => agent.applyCandidate(candidate.candidate_id))}
                              >
                                Apply
                              </Button>
                            ) : (
                              <Button
                                disabled={isBusy || !tts.status?.stats.running}
                                onClick={() => runAction(() => agent.speakCandidate(candidate.candidate_id))}
                              >
                                <Volume2 className="h-4 w-4" />
                                Speak
                              </Button>
                            )}
                            <Button
                              variant="secondary"
                              disabled={isBusy}
                              onClick={() => runAction(() => agent.dismissCandidate(candidate.candidate_id))}
                            >
                              <X className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))
                ) : (
                  <div className="px-3 py-3 text-xs text-muted-foreground">No candidates yet</div>
                )}
              </div>
            </div>

            <div className="rounded-md border border-border bg-background">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">Reasoning</div>
              <div className="max-h-40 overflow-auto">
                {agentStatus.reasoning_traces.length ? (
                  agentStatus.reasoning_traces
                    .slice()
                    .reverse()
                    .slice(0, surface === "popup" ? 2 : 5)
                    .map((trace) => (
                      <ReasoningTraceRow trace={trace} key={trace.trace_id} />
                    ))
                ) : (
                  <div className="px-3 py-3 text-xs text-muted-foreground">No reasoning traces yet</div>
                )}
              </div>
            </div>

            <div className="rounded-md border border-border bg-background">
              <div className="border-b border-border px-3 py-2 text-xs font-medium">Provider calls</div>
              <div className="max-h-36 overflow-auto">
                {agentStatus.llm_call_traces.length ? (
                  agentStatus.llm_call_traces
                    .slice()
                    .reverse()
                    .slice(0, surface === "popup" ? 2 : 5)
                    .map((trace) => <LLMCallTraceRow trace={trace} key={trace.trace_id} />)
                ) : (
                  <div className="px-3 py-3 text-xs text-muted-foreground">No provider calls yet</div>
                )}
              </div>
            </div>

            <label className="block space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  Aggressiveness
                </span>
                <span>{agentStatus.settings.aggressiveness}%</span>
              </div>
              <Slider
                min={0}
                max={100}
                step={5}
                value={agentStatus.settings.aggressiveness}
                onChange={(event) => {
                  const aggressiveness = Number(event.currentTarget.value);
                  updateSettings({ aggressiveness });
                  void runAction(() => agent.setAggressiveness(aggressiveness));
                }}
              />
            </label>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <label className="block space-y-1">
                <span className="text-muted-foreground">Silence gap (s)</span>
                <input
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 outline-none focus:border-primary"
                  min={0}
                  max={30}
                  step={0.1}
                  type="number"
                  value={formatSeconds(agentStatus.settings.proactive_min_silence_ms)}
                  onChange={(event) => {
                    const proactive_min_silence_ms = Number(event.currentTarget.value) * 1000;
                    const aggressiveness = agentStatus.settings.aggressiveness;
                    void runAction(() =>
                      agent.setPolicy({ aggressiveness, proactive_min_silence_ms })
                    );
                  }}
                />
              </label>
              <label className="block space-y-1">
                <span className="text-muted-foreground">Cooldown (s)</span>
                <input
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 outline-none focus:border-primary"
                  min={0}
                  max={120}
                  step={0.5}
                  type="number"
                  value={formatSeconds(agentStatus.settings.direct_answer_cooldown_ms)}
                  onChange={(event) => {
                    const direct_answer_cooldown_ms = Number(event.currentTarget.value) * 1000;
                    const aggressiveness = agentStatus.settings.aggressiveness;
                    void runAction(() =>
                      agent.setPolicy({ aggressiveness, direct_answer_cooldown_ms })
                    );
                  }}
                />
              </label>
            </div>

            <StatusLine text={agent.error ?? agent.status?.status.last_error ?? agent.endpointUrl} danger={Boolean(agent.error || agent.status?.status.last_error)} />
            <StatusLine
              text={
                agentStatus.readiness.blockers.length
                  ? `Auto-speak blocked: ${agentStatus.readiness.blockers.join(", ")}`
                  : undefined
              }
              danger
            />

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

function ReasoningTraceRow({ trace }: { trace: AgentReasoningTrace }) {
  const label = trace.error ? "error" : trace.action?.replaceAll("_", " ") ?? "decision";
  const detail = trace.error ?? trace.reason ?? "No rationale captured";
  return (
    <div className="space-y-1 border-b border-border px-3 py-2 last:border-b-0">
      <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span className={trace.error ? "font-medium text-danger" : "font-medium text-foreground"}>
          {label}
        </span>
        <span>{trace.score == null ? "--" : `${Math.round(trace.score * 100)}%`}</span>
      </div>
      <p className="text-xs leading-5 text-foreground">{detail}</p>
      <p className="text-[11px] leading-4 text-muted-foreground">
        {[
          trace.candidate_type?.replaceAll("_", " "),
          trace.suggested_mode ? `mode: ${modeLabels[trace.suggested_mode]}` : undefined,
          trace.can_auto_speak ? "auto ready" : "manual",
          trace.cooldown_allows_speech ? "cooldown clear" : "cooldown",
          `${trace.recent_utterance_count} utt`
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </div>
  );
}

function LLMCallTraceRow({ trace }: { trace: AgentLLMCallTrace }) {
  const detail = trace.error ?? trace.output_preview ?? trace.input_preview ?? "No preview captured";
  return (
    <div className="space-y-1 border-b border-border px-3 py-2 last:border-b-0">
      <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span className={trace.success ? "font-medium text-foreground" : "font-medium text-danger"}>
          {trace.operation.replaceAll("_", " ")}
        </span>
        <span>{Math.round(trace.latency_ms)}ms</span>
      </div>
      <p className="text-xs leading-5 text-foreground">{detail}</p>
      <p className="text-[11px] leading-4 text-muted-foreground">{trace.provider}</p>
    </div>
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

function normalizeAgentStatus(payload: AgentStatusPayload | undefined): AgentStatusPayload["status"] {
  const status = payload?.status;
  return {
    name: status?.name ?? "Erica",
    mode: status?.mode ?? "passive",
    lifecycle_state: status?.lifecycle_state ?? "not_in_meeting",
    runtime_state: status?.runtime_state ?? "idle_listening",
    meeting_id: status?.meeting_id ?? null,
    meeting_url: status?.meeting_url ?? null,
    recent_utterances: status?.recent_utterances ?? [],
    participants: status?.participants ?? [],
    requirements: status?.requirements ?? [],
    open_questions: status?.open_questions ?? [],
    decisions: status?.decisions ?? [],
    action_items: status?.action_items ?? [],
    risks: status?.risks ?? [],
    parked_topics: status?.parked_topics ?? [],
    context_summaries: status?.context_summaries ?? [],
    current_topic: status?.current_topic ?? null,
    candidate_interventions: status?.candidate_interventions ?? [],
    reasoning_traces: status?.reasoning_traces ?? [],
    llm_call_traces: status?.llm_call_traces ?? [],
    latest_summary: status?.latest_summary ?? null,
    settings: {
      aggressiveness: status?.settings?.aggressiveness ?? 25,
      direct_answer_cooldown_ms: status?.settings?.direct_answer_cooldown_ms ?? 8_000,
      proactive_min_silence_ms: status?.settings?.proactive_min_silence_ms ?? 1_200
    },
    readiness: {
      can_auto_speak: status?.readiness?.can_auto_speak ?? false,
      blockers: status?.readiness?.blockers ?? ["agent status is still loading"]
    },
    active_speech_job_id: status?.active_speech_job_id ?? null,
    last_speech_job_id: status?.last_speech_job_id ?? null,
    last_agent_speech_at_ms: status?.last_agent_speech_at_ms ?? null,
    last_human_speech_at_ms: status?.last_human_speech_at_ms ?? null,
    last_state_change_at_ms: status?.last_state_change_at_ms ?? Date.now(),
    last_error: status?.last_error ?? null
  };
}

function CompactRecordList({
  emptyText,
  items,
  title
}: {
  emptyText: string;
  items: string[];
  title: string;
}) {
  return (
    <div className="rounded-md border border-border bg-background">
      <div className="border-b border-border px-3 py-2 text-xs font-medium">{title}</div>
      <div className="max-h-32 overflow-auto">
        {items.length ? (
          items
            .slice()
            .reverse()
            .slice(0, 5)
            .map((item, index) => (
              <div className="border-b border-border px-3 py-2 text-xs leading-5 last:border-b-0" key={`${item}-${index}`}>
                {item}
              </div>
            ))
        ) : (
          <div className="px-3 py-3 text-xs text-muted-foreground">{emptyText}</div>
        )}
      </div>
    </div>
  );
}

function formatRequirementDetails(requirement: RequirementRecord): string {
  const constraints = requirement.constraints ?? [];
  const acceptanceCriteria = requirement.acceptance_criteria ?? [];
  const details = [
    requirement.actor ? `actor: ${requirement.actor}` : undefined,
    requirement.behavior ? `behavior: ${requirement.behavior}` : undefined,
    requirement.goal ? `goal: ${requirement.goal}` : undefined,
    requirement.priority !== "unknown" ? `priority: ${requirement.priority}` : undefined,
    requirement.owner ? `owner: ${requirement.owner}` : undefined,
    requirement.status !== "proposed" ? `status: ${requirement.status}` : undefined,
    constraints.length ? `constraints: ${constraints.join(", ")}` : undefined,
    acceptanceCriteria.length
      ? `acceptance: ${acceptanceCriteria.join(", ")}`
      : undefined
  ].filter(Boolean);
  return details.length ? details.join(" · ") : "details pending";
}

function formatOpenQuestion(question: import("./messages").OpenQuestionRecord): string {
  const status = question.answered ? "answered" : "open";
  const relatedRequirementIds = question.related_requirement_ids ?? [];
  if (!relatedRequirementIds.length) {
    return `${question.text} · ${status}`;
  }
  const suffix =
    relatedRequirementIds.length === 1
      ? "1 linked requirement"
      : `${relatedRequirementIds.length} linked requirements`;
  return `${question.text} · ${status} · ${suffix}`;
}

function formatDecision(decision: import("./messages").DecisionRecord): string {
  return `${decision.text} · ${decision.confirmed ? "confirmed" : "unconfirmed"}`;
}

function formatActionItem(actionItem: import("./messages").ActionItemRecord): string {
  const details = [
    actionItem.completed ? "completed" : "open",
    actionItem.owner ? `owner: ${actionItem.owner}` : undefined
  ].filter(Boolean);
  return `${actionItem.text} · ${details.join(" · ")}`;
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

function isOutputDeviceVisible(
  status: import("./messages").AudioDevicesStatus | undefined,
  expected: string | null | undefined
): boolean {
  if (!status?.ok || !expected) {
    return false;
  }
  const value = expected.trim().toLowerCase();
  if (!value) {
    return false;
  }
  if (/^\d+$/.test(value)) {
    const index = Number(value);
    return status.output_devices.some((device) => device.index === index);
  }
  return status.output_devices.some((device) => device.name.toLowerCase().includes(value));
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

function formatSeconds(valueMs: number | undefined): string {
  if (valueMs === undefined) {
    return "0";
  }
  return String(Math.round((valueMs / 1000) * 10) / 10);
}

function formatCount(value: number | undefined): string {
  if (value == null) {
    return "--";
  }
  return value.toLocaleString();
}

function formatConfidence(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  return `${Math.round(value * 100)}%`;
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

function formatState(value: string | undefined): string {
  if (!value) {
    return "--";
  }
  return value.replaceAll("_", " ");
}
