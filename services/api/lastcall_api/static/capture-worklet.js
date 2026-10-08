/**
 * AudioWorkletProcessor for capturing microphone input:
 * - Resamples from browser sampleRate to 16 kHz PCM
 * - Converts Float32 to Int16 Little Endian
 * - Emits 1,600-sample chunks (100 ms at 16 kHz = 3,200 bytes)
 */
class CaptureWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.buffer = new Float32Array(0);
    this.chunkSize = 1600; // 100 ms of 16 kHz audio
    this.resampleRatio = this.targetRate / sampleRate;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) {
      return true;
    }

    const channelData = input[0];

    // Simple linear interpolation downsampling to 16 kHz
    const newLen = Math.floor(channelData.length * this.resampleRatio);
    const resampled = new Float32Array(newLen);
    for (let i = 0; i < newLen; i++) {
      const srcIdx = i / this.resampleRatio;
      const idxFloor = Math.floor(srcIdx);
      const idxCeil = Math.min(channelData.length - 1, idxFloor + 1);
      const weight = srcIdx - idxFloor;
      resampled[i] = channelData[idxFloor] * (1 - weight) + channelData[idxCeil] * weight;
    }

    // Append to internal accumulation buffer
    const merged = new Float32Array(this.buffer.length + resampled.length);
    merged.set(this.buffer);
    merged.set(resampled, this.buffer.length);
    this.buffer = merged;

    // Emit 1,600-sample chunks
    while (this.buffer.length >= this.chunkSize) {
      const chunk = this.buffer.slice(0, this.chunkSize);
      this.buffer = this.buffer.slice(this.chunkSize);

      // Convert Float32 [-1.0, 1.0] to Int16 LE
      const int16Array = new Int16Array(this.chunkSize);
      for (let j = 0; j < this.chunkSize; j++) {
        const s = Math.max(-1.0, Math.min(1.0, chunk[j]));
        int16Array[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }

      this.port.postMessage(int16Array.buffer, [int16Array.buffer]);
    }

    return true;
  }
}

registerProcessor('capture-worklet', CaptureWorkletProcessor);
