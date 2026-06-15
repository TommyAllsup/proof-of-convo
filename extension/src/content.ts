import type {
  ContentCaptureRequest,
  StartContentMicCaptureRequest,
  StatusUpdateMessage
} from "./shared/messages";

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

interface WorkletPcmMessage {
  type: "pcm";
  pcm16: ArrayBuffer;
  sampleRate: number;
  frameCount: number;
  rms: number;
  peak: number;
}

const AUDIO_PACKET_MAGIC = 0x504f4341;
const AUDIO_PACKET_VERSION = 2;
const AUDIO_PACKET_HEADER_BYTES = 52;
const MIC_SOURCE_ID = 2;

interface EncodeMicAudioPacketInput {
  sequence: number;
  tabId: number;
  captureStartedAtMs: number;
  chunkStartedAtMs: number;
  clientSentAtMs: number;
  sampleRate: number;
  pcm16: ArrayBuffer;
}

function encodeMicAudioPacket(input: EncodeMicAudioPacketInput): ArrayBuffer {
  const packet = new ArrayBuffer(AUDIO_PACKET_HEADER_BYTES + input.pcm16.byteLength);
  const view = new DataView(packet);
  view.setUint32(0, AUDIO_PACKET_MAGIC, false);
  view.setUint16(4, AUDIO_PACKET_VERSION, false);
  view.setUint16(6, AUDIO_PACKET_HEADER_BYTES, false);
  view.setUint32(8, input.sequence, false);
  view.setUint32(12, input.tabId >>> 0, false);
  view.setFloat64(16, input.captureStartedAtMs, false);
  view.setFloat64(24, input.chunkStartedAtMs, false);
  view.setFloat64(32, input.clientSentAtMs, false);
  view.setUint32(40, input.sampleRate, false);
  view.setUint32(44, input.pcm16.byteLength, false);
  view.setUint8(48, MIC_SOURCE_ID);
  new Uint8Array(packet, AUDIO_PACKET_HEADER_BYTES).set(new Uint8Array(input.pcm16));
  return packet;
}

class ContentMicCapture {
  private audioContext?: AudioContext;
  private stream?: MediaStream;
  private source?: MediaStreamAudioSourceNode;
  private worklet?: AudioWorkletNode;
  private monitorGain?: GainNode;
  private socket?: WebSocket;
  private sessionId?: string;
  private sequence = 0;
  private captureStartedAtMs = 0;

  async start(request: StartContentMicCaptureRequest): Promise<void> {
    await this.stop("restart");
    this.sessionId = `${request.sessionId}:mic`;
    this.sequence = 0;
    this.captureStartedAtMs = Date.now();
    this.socket = new WebSocket(request.backendWsUrl);
    this.socket.binaryType = "arraybuffer";
    this.socket.addEventListener("open", () => {
      this.socket?.send(
        JSON.stringify({
          type: "session_start",
          session_id: this.sessionId,
          tab_id: request.tabId,
          meeting_url: `${request.meetingUrl}#source=mic`,
          sample_rate: 16_000,
          chunk_ms: 200,
          client_started_at_ms: this.captureStartedAtMs,
          client_sent_at_ms: Date.now(),
          telemetry_enabled: request.telemetryEnabled,
          audio_source: "mic"
        })
      );
    });
    this.socket.addEventListener("error", () => {
      this.postStatus({ captureState: "error", backendState: "error", error: "Mic socket error." });
    });

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      },
      video: false
    });
    this.audioContext = new AudioContext();
    await this.audioContext.audioWorklet.addModule(chrome.runtime.getURL("assets/pcm-worklet.js"));
    this.source = this.audioContext.createMediaStreamSource(this.stream);
    this.worklet = new AudioWorkletNode(this.audioContext, "pcm-worklet", {
      processorOptions: { targetSampleRate: 16_000, chunkMs: 200 }
    });
    this.monitorGain = this.audioContext.createGain();
    this.monitorGain.gain.value = 0;
    this.source.connect(this.worklet);
    this.worklet.connect(this.monitorGain).connect(this.audioContext.destination);
    this.worklet.port.onmessage = (event: MessageEvent<WorkletPcmMessage>) =>
      this.handlePcm(event.data, request.tabId);
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }

    this.postStatus({ error: undefined });
  }

  async stop(reason: string): Promise<void> {
    if (this.sessionId && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(
        JSON.stringify({
          type: "session_stop",
          session_id: this.sessionId,
          reason,
          client_sent_at_ms: Date.now()
        })
      );
    }
    this.socket?.close();
    this.socket = undefined;
    this.sessionId = undefined;
    this.worklet?.disconnect();
    this.monitorGain?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.audioContext && this.audioContext.state !== "closed") {
      await this.audioContext.close();
    }
    this.audioContext = undefined;
    this.stream = undefined;
    this.source = undefined;
    this.worklet = undefined;
    this.monitorGain = undefined;
  }

  private handlePcm(message: WorkletPcmMessage, tabId: number): void {
    if (message.type !== "pcm" || this.socket?.readyState !== WebSocket.OPEN) {
      return;
    }
    const clientSentAtMs = Date.now();
    const chunkDurationMs = (message.frameCount / message.sampleRate) * 1000.0;
    this.socket.send(
      encodeMicAudioPacket({
        sequence: this.sequence,
        tabId,
        captureStartedAtMs: this.captureStartedAtMs,
        chunkStartedAtMs: clientSentAtMs - chunkDurationMs,
        clientSentAtMs,
        sampleRate: message.sampleRate,
        pcm16: message.pcm16
      })
    );
    this.sequence += 1;
  }

  private postStatus(status: Partial<StatusUpdateMessage["status"]>): void {
    chrome.runtime.sendMessage({ type: "OFFSCREEN_STATUS", status }).catch(() => undefined);
  }
}

const micCapture = new ContentMicCapture();

chrome.runtime.onMessage.addListener((message: ContentCaptureRequest) => {
  if (message.target !== "content") {
    return;
  }

  if (message.type === "START_CONTENT_MIC_CAPTURE") {
    micCapture.start(message).catch((error: unknown) => {
      const messageText = error instanceof Error ? error.message : String(error);
      chrome.runtime
        .sendMessage({
          type: "OFFSCREEN_STATUS",
          status: {
            captureState: "error",
            backendState: "error",
            error: `Local mic capture failed: ${messageText}`
          }
        })
        .catch(() => undefined);
    });
  }

  if (message.type === "STOP_CONTENT_MIC_CAPTURE") {
    micCapture.stop(message.reason ?? "user_stop").catch(() => undefined);
  }
});
