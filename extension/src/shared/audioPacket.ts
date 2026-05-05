export const AUDIO_PACKET_MAGIC = 0x504f4331;
export const AUDIO_PACKET_VERSION = 1;
export const AUDIO_PACKET_HEADER_BYTES = 48;

export interface EncodeAudioPacketInput {
  sequence: number;
  tabId: number;
  captureStartedAtMs: number;
  chunkStartedAtMs: number;
  clientSentAtMs: number;
  sampleRate: number;
  pcm16: ArrayBuffer;
}

export function encodeAudioPacket(input: EncodeAudioPacketInput): ArrayBuffer {
  const sampleCount = input.pcm16.byteLength / 2;
  if (!Number.isInteger(sampleCount)) {
    throw new Error("PCM16 buffers must contain complete 16-bit samples.");
  }

  const packet = new ArrayBuffer(AUDIO_PACKET_HEADER_BYTES + input.pcm16.byteLength);
  const view = new DataView(packet);
  view.setUint32(0, AUDIO_PACKET_MAGIC, false);
  view.setUint16(4, AUDIO_PACKET_VERSION, false);
  view.setUint16(6, AUDIO_PACKET_HEADER_BYTES, false);
  view.setUint32(8, input.sequence, false);
  view.setUint32(12, input.tabId, false);
  view.setFloat64(16, input.captureStartedAtMs, false);
  view.setFloat64(24, input.chunkStartedAtMs, false);
  view.setFloat64(32, input.clientSentAtMs, false);
  view.setUint32(40, input.sampleRate, false);
  view.setUint32(44, sampleCount, false);
  new Uint8Array(packet, AUDIO_PACKET_HEADER_BYTES).set(new Uint8Array(input.pcm16));
  return packet;
}

