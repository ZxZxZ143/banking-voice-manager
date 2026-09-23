class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = new Int16Array(2400);
    this.used = 0;
    this.stopped = false;
    this.port.onmessage = ({ data }) => {
      if (data === 'finish') {
        if (this.used) this.port.postMessage(this.samples.slice(0, this.used).buffer);
        this.stopped = true;
        this.port.postMessage('flushed');
      }
    };
  }
  process(inputs) {
    if (this.stopped) return false;
    const channel = inputs[0]?.[0];
    if (channel) {
      for (const value of channel) {
        this.samples[this.used++] = Math.round(Math.max(-1, Math.min(1, value)) * 32767);
        if (this.used === this.samples.length) {
          this.port.postMessage(this.samples.buffer, [this.samples.buffer]);
          this.samples = new Int16Array(2400);
          this.used = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PcmCapture);
