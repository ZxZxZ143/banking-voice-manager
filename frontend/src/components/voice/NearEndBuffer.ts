/** 400 ms PCM24 ring, RAM only. Never armed without a decoded playback reference.
 * The browser's acoustic echo cancellation is primary; this gate additionally
 * rejects silence and strongly correlated speaker echo, including delayed echo.
 */
export class NearEndBuffer {
  private frames: ArrayBuffer[] = [];
  private size = 0;
  private reference: Float32Array | null = null;
  private playbackSeconds = 0;
  private playbackAt = 0;
  private armed = false;
  readonly maxBytes = 24_000 * 2 * 0.4;
  constructor(private readonly onEcho?: () => void) {}

  setReference(reference: Float32Array) {
    this.reference = reference;
  }
  arm(seconds: number, at = performance.now()) {
    if (!this.reference) return;
    this.armed = true;
    this.playbackSeconds = seconds;
    this.playbackAt = at;
  }
  push(frame: ArrayBuffer, now = performance.now()) {
    if (!this.armed || !this.reference) return;
    this.frames.push(this.filter(frame, now));
    this.size += frame.byteLength;
    while (this.size > this.maxBytes && this.frames.length)
      this.size -= this.frames.shift()!.byteLength;
  }
  filter(frame: ArrayBuffer, now = performance.now()): ArrayBuffer {
    if (!this.reference) return frame;
    const pcm = new Int16Array(frame);
    let energy = 0;
    for (const sample of pcm) energy += (sample / 32768) ** 2;
    const rms = Math.sqrt(energy / pcm.length);
    if (rms < 0.008) return new ArrayBuffer(frame.byteLength);
    // Frame timestamp is its end (worklet delivers after accumulation).
    const end = this.playbackSeconds + (now - this.playbackAt) / 1000;
    let echo = false;
    // Two AudioContexts / hardware pipelines can differ slightly in their clock
    // alignment. Search sample offsets, not 5 ms steps that miss voiced speech.
    for (let delay = -0.08; delay <= 0.3 && !echo; delay += 4 / 24000) {
      const start = Math.round((end - delay) * 24000) - pcm.length;
      let dot = 0,
        left = 0,
        right = 0;
      for (let i = 0; i < pcm.length; i += 4) {
        const a = pcm[i] / 32768,
          b = this.reference[start + i] ?? 0;
        dot += a * b;
        left += a * a;
        right += b * b;
      }
      echo =
        left > 0 && right > 0 && Math.abs(dot) / Math.sqrt(left * right) > 0.65;
    }
    // Keep frame duration but never send recognized echo as caller speech.
    if (echo) this.onEcho?.();
    return echo ? new ArrayBuffer(frame.byteLength) : frame.slice(0);
  }
  take(retainEchoTail = false): ArrayBuffer[] {
    const frames = this.frames;
    this.frames = [];
    this.size = 0;
    this.armed = false;
    if (!retainEchoTail) this.reference = null;
    return frames.some((frame) =>
      new Int16Array(frame).some((value) => value !== 0),
    )
      ? frames
      : [];
  }
  clear() {
    this.frames = [];
    this.size = 0;
    this.reference = null;
    this.armed = false;
  }
}
