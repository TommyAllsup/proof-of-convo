declare const sampleRate: number;

declare class AudioWorkletProcessor {
  readonly port: MessagePort;
  process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>
  ): boolean;
}

declare function registerProcessor(
  name: string,
  processorCtor: {
    new (options?: AudioWorkletNodeOptions): AudioWorkletProcessor;
  }
): void;

interface PcmWorkletOptions extends AudioWorkletNodeOptions {
  processorOptions?: {
    targetSampleRate?: number;
    chunkMs?: number;
  };
}

class PcmWorkletProcessor extends AudioWorkletProcessor {
  private readonly targetSampleRate: number;
  private readonly chunkFrames: number;
  private readonly sourceFramesPerChunk: number;
  private pending: number[] = [];

  constructor(options?: PcmWorkletOptions) {
    super();
    this.targetSampleRate = options?.processorOptions?.targetSampleRate ?? 16_000;
    const chunkMs = options?.processorOptions?.chunkMs ?? 200;
    this.chunkFrames = Math.max(1, Math.round((this.targetSampleRate * chunkMs) / 1000));
    this.sourceFramesPerChunk = Math.max(
      1,
      Math.round(this.chunkFrames * (sampleRate / this.targetSampleRate))
    );
  }

  override process(inputs: Float32Array[][]): boolean {
    const input = inputs[0];
    if (!input || input.length === 0 || input[0].length === 0) {
      return true;
    }

    const channelCount = input.length;
    const frameCount = input[0].length;
    for (let frame = 0; frame < frameCount; frame += 1) {
      let sum = 0;
      for (let channel = 0; channel < channelCount; channel += 1) {
        sum += input[channel][frame] ?? 0;
      }
      this.pending.push(sum / channelCount);
    }

    while (this.pending.length >= this.sourceFramesPerChunk) {
      this.emitChunk();
    }

    if (this.pending.length > this.sourceFramesPerChunk * 4) {
      this.pending = this.pending.slice(-this.sourceFramesPerChunk);
    }

    return true;
  }

  private emitChunk(): void {
    const ratio = this.sourceFramesPerChunk / this.chunkFrames;
    const output = new Int16Array(this.chunkFrames);
    let energy = 0;
    let peak = 0;

    for (let frame = 0; frame < this.chunkFrames; frame += 1) {
      const sourceIndex = Math.min(Math.floor(frame * ratio), this.pending.length - 1);
      const sample = Math.max(-1, Math.min(1, this.pending[sourceIndex] ?? 0));
      peak = Math.max(peak, Math.abs(sample));
      energy += sample * sample;
      output[frame] = sample < 0 ? Math.round(sample * 32768) : Math.round(sample * 32767);
    }

    this.pending = this.pending.slice(this.sourceFramesPerChunk);
    this.port.postMessage(
      {
        type: "pcm",
        pcm16: output.buffer,
        sampleRate: this.targetSampleRate,
        frameCount: output.length,
        rms: Math.sqrt(energy / output.length),
        peak
      },
      [output.buffer]
    );
  }
}

registerProcessor("pcm-worklet", PcmWorkletProcessor);

