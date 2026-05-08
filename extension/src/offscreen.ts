import { encodeAudioPacket } from "./shared/audioPacket";
import type {
  RuntimeStatus,
  StartOffscreenCaptureRequest,
  StopOffscreenCaptureRequest
} from "./shared/messages";

interface WorkletPcmMessage {
  type: "pcm";
  pcm16: ArrayBuffer;
  sampleRate: number;
  frameCount: number;
  rms: number;
  peak: number;
}

class BackendSocket {
  private socket?: WebSocket;
  private reconnectTimer?: number;
  private readonly queue: Array<ArrayBuffer | string> = [];
  private reconnectAttempt = 0;

  constructor(
    private readonly url: string,
    private readonly onStatus: (status: Partial<RuntimeStatus>) => void
  ) {}

  connect(): void {
    this.onStatus({ backendState: "connecting" });
    this.socket = new WebSocket(this.url);
    this.socket.binaryType = "arraybuffer";

    this.socket.addEventListener("open", () => {
      this.reconnectAttempt = 0;
      this.onStatus({ backendState: "connected", error: undefined });
      this.flush();
    });

    this.socket.addEventListener("message", (event) => {
      if (typeof event.data !== "string") {
        return;
      }
      const payload = JSON.parse(event.data) as Record<string, unknown>;
      if (payload.type === "chunk_ack") {
        this.onStatus({
          backendState: "connected",
          sequence: payload.sequence as number,
          latencyMs: payload.latency_ms as number,
          rms: payload.rms as number,
          peak: payload.peak as number,
          droppedChunks: payload.dropped_chunks as number,
          queuedChunks: payload.queued_chunks as number
        });
      } else if (payload.type === "session_ack") {
        this.onStatus({ backendState: "connected", error: undefined });
      } else if (payload.type === "error") {
        this.onStatus({ backendState: "error", error: String(payload.message) });
      }
    });

    this.socket.addEventListener("close", () => this.scheduleReconnect());
    this.socket.addEventListener("error", () => {
      this.onStatus({ backendState: "error", error: "Backend WebSocket error." });
    });
  }

  sendJson(payload: unknown): void {
    this.send(JSON.stringify(payload));
  }

  sendBinary(payload: ArrayBuffer): void {
    this.send(payload);
  }

  close(): void {
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
    }
    this.socket?.close();
    this.socket = undefined;
    this.queue.length = 0;
  }

  private send(payload: ArrayBuffer | string): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(payload);
      return;
    }

    this.queue.push(payload);
    if (this.queue.length > 150) {
      this.queue.shift();
    }
    this.onStatus({ backendState: "buffering", queuedChunks: this.queue.length });
  }

  private flush(): void {
    while (this.queue.length && this.socket?.readyState === WebSocket.OPEN) {
      const payload = this.queue.shift();
      if (payload !== undefined) {
        this.socket.send(payload);
      }
    }
  }

  private scheduleReconnect(): void {
    if (!this.socket) {
      return;
    }
    this.onStatus({ backendState: "disconnected" });
    const delayMs = Math.min(5000, 250 * 2 ** this.reconnectAttempt);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => this.connect(), delayMs);
  }
}

class CaptureController {
  private audioContext?: AudioContext;
  private mediaStream?: MediaStream;
  private socket?: BackendSocket;
  private source?: MediaStreamAudioSourceNode;
  private worklet?: AudioWorkletNode;
  private monitorGain?: GainNode;
  private sessionId?: string;
  private sequence = 0;
  private captureStartedAtMs = Date.now();
  private lastStatusAtMs = 0;

  async start(request: StartOffscreenCaptureRequest): Promise<void> {
    await this.stop("restart");

    this.captureStartedAtMs = Date.now();
    this.sequence = 0;
    this.sessionId = request.sessionId;
    this.socket = new BackendSocket(request.backendWsUrl, (status) => this.postStatus(status));
    this.socket.connect();
    this.socket.sendJson({
      type: "session_start",
      session_id: request.sessionId,
      tab_id: request.tabId,
      meeting_url: request.meetingUrl,
      sample_rate: 16_000,
      chunk_ms: 200,
      client_started_at_ms: this.captureStartedAtMs,
      client_sent_at_ms: Date.now(),
      telemetry_enabled: request.telemetryEnabled
    });

    const constraints = {
      audio: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: request.streamId
        }
      },
      video: false
    } as MediaStreamConstraints;

    this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
    this.mediaStream.getAudioTracks().forEach((track) => {
      track.addEventListener("ended", () => {
        this.postStatus({
          captureState: "error",
          backendState: "disconnected",
          error: "Tab capture track ended."
        });
        this.stop("track_ended").catch(() => undefined);
      });
    });

    this.audioContext = new AudioContext();
    await this.audioContext.audioWorklet.addModule(chrome.runtime.getURL("assets/pcm-worklet.js"));
    this.source = this.audioContext.createMediaStreamSource(this.mediaStream);

    const monitor = this.audioContext.createMediaStreamSource(this.mediaStream);
    monitor.connect(this.audioContext.destination);

    this.worklet = new AudioWorkletNode(this.audioContext, "pcm-worklet", {
      processorOptions: { targetSampleRate: 16_000, chunkMs: 200 }
    });
    this.monitorGain = this.audioContext.createGain();
    this.monitorGain.gain.value = 0;

    this.source.connect(this.worklet);
    this.worklet.connect(this.monitorGain).connect(this.audioContext.destination);
    this.worklet.port.onmessage = (event: MessageEvent<WorkletPcmMessage>) =>
      this.handlePcmChunk(event.data, request);

    this.postStatus({
      captureState: "streaming",
      backendState: "connecting",
      activeTabId: request.tabId,
      meetingUrl: request.meetingUrl,
      sessionId: request.sessionId,
      error: undefined
    });
  }

  async stop(reason: string): Promise<void> {
    if (this.sessionId) {
      this.socket?.sendJson({
        type: "session_stop",
        session_id: this.sessionId,
        reason,
        client_sent_at_ms: Date.now()
      });
    }
    this.socket?.close();
    this.socket = undefined;
    this.sessionId = undefined;

    this.worklet?.disconnect();
    this.monitorGain?.disconnect();
    this.source?.disconnect();
    this.mediaStream?.getTracks().forEach((track) => track.stop());

    if (this.audioContext && this.audioContext.state !== "closed") {
      await this.audioContext.close();
    }

    this.audioContext = undefined;
    this.mediaStream = undefined;
    this.source = undefined;
    this.worklet = undefined;
    this.monitorGain = undefined;

    this.postStatus({
      captureState: "idle",
      backendState: "disconnected",
      clientRms: 0,
      rms: 0,
      peak: 0
    });
  }

  private handlePcmChunk(message: WorkletPcmMessage, request: StartOffscreenCaptureRequest): void {
    if (message.type !== "pcm" || !this.socket) {
      return;
    }

    const clientSentAtMs = Date.now();
    const chunkDurationMs = (message.frameCount / message.sampleRate) * 1000.0;
    const packet = encodeAudioPacket({
      sequence: this.sequence,
      tabId: request.tabId,
      captureStartedAtMs: this.captureStartedAtMs,
      chunkStartedAtMs: clientSentAtMs - chunkDurationMs,
      clientSentAtMs,
      sampleRate: message.sampleRate,
      pcm16: message.pcm16
    });
    this.socket.sendBinary(packet);
    this.sequence += 1;

    if (clientSentAtMs - this.lastStatusAtMs >= 250) {
      this.postStatus({
        captureState: "streaming",
        clientRms: message.rms,
        peak: message.peak,
        sequence: this.sequence
      });
      this.lastStatusAtMs = clientSentAtMs;
    }
  }

  private postStatus(status: Partial<RuntimeStatus>): void {
    chrome.runtime
      .sendMessage({
        type: "OFFSCREEN_STATUS",
        status
      })
      .catch(() => undefined);
  }
}

const controller = new CaptureController();

chrome.runtime.onMessage.addListener(
  (message: StartOffscreenCaptureRequest | StopOffscreenCaptureRequest) => {
    if (message.target !== "offscreen") {
      return;
    }

    if (message.type === "START_OFFSCREEN_CAPTURE") {
      controller.start(message).catch((error: unknown) => {
        chrome.runtime
          .sendMessage({
            type: "OFFSCREEN_STATUS",
            status: {
              captureState: "error",
              backendState: "error",
              error: error instanceof Error ? error.message : String(error)
            }
          })
          .catch(() => undefined);
      });
    }

    if (message.type === "STOP_OFFSCREEN_CAPTURE") {
      controller.stop(message.reason ?? "user_stop").catch(() => undefined);
    }
  }
);
