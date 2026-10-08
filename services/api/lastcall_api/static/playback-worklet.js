/**
 * AudioWorkletProcessor for 24 kHz Gemini Live playback:
 * - Queues incoming 24 kHz PCM Int16 or Float32 samples
 * - Resamples to browser sampleRate if context rate differs from 24 kHz
 * - Immediately clears buffer on "clear" message (interruption)
 */
class PlaybackWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sourceRate = 24000;
    this.buffer = new Float32Array(0);
    this.resampleRatio = sampleRate / this.sourceRate; // context rate / 24000

    this.port.onmessage = (event) => {
      const data = event.data;
      if (data && data.type === 'clear') {
        // Interruption: immediately flush the playback buffer
        this.buffer = new Float32Array(0);
        return;
      }

      if (data instanceof ArrayBuffer || data.buffer instanceof ArrayBuffer) {
        // Raw Int16 PCM from Gemini
        const rawBytes = data instanceof ArrayBuffer ? data : data.buffer;
        const int16 = new Int16Array(rawBytes);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) {
          float32[i] = int16[i] / 32768.0;
        }

        // Resample if context sample rate is not 24 kHz (e.g. Safari on 44.1k/48k)
        let toQueue = float32;
        if (Math.abs(sampleRate - this.sourceRate) > 100) {
          const outLen = Math.floor(float32.length * this.resampleRatio);
          const resampled = new Float32Array(outLen);
          for (let i = 0; i < outLen; i++) {
            const srcIdx = i / this.resampleRatio;
            const idxFloor = Math.floor(srcIdx);
            const idxCeil = Math.min(float32.length - 1, idxFloor + 1);
            const weight = srcIdx - idxFloor;
            resampled[i] = float32[idxFloor] * (1 - weight) + float32[idxCeil] * weight;
          }
          toQueue = resampled;
        }

        // Append to playback buffer
        const merged = new Float32Array(this.buffer.length + toQueue.length);
        merged.set(this.buffer);
        merged.set(toQueue, this.buffer.length);
        this.buffer = merged;
      }
    };
  }

  process(inputs, outputs, parameters) {
    const output = outputs[0];
    if (!output || !output[0]) {
      return true;
    }

    const channelData = output[0];
    const needed = channelData.length;

    if (this.buffer.length >= needed) {
      channelData.set(this.buffer.subarray(0, needed));
      this.buffer = this.buffer.slice(needed);
    } else if (this.buffer.length > 0) {
      channelData.set(this.buffer);
      channelData.fill(0, this.buffer.length);
      this.buffer = new Float32Array(0);
    } else {
      channelData.fill(0);
    }

    return true;
  }
}

registerProcessor('playback-worklet', PlaybackWorkletProcessor);
