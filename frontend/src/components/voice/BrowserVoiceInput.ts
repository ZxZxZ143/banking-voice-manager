import { NearEndBuffer } from "./NearEndBuffer.ts";
import { voiceTiming } from "../../runtime/voiceTiming.ts";

type VoiceEvent = { type: string; [key: string]: unknown };
type Run = {
  cancelled: boolean;
  sending: boolean;
  ready: Promise<void>;
  resolve: () => void;
  reject: (error: Error) => void;
  ws?: WebSocket;
  node?: AudioWorkletNode;
  source?: MediaStreamAudioSourceNode;
  mute?: GainNode;
  deadline?: ReturnType<typeof setTimeout>;
  ring: NearEndBuffer;
  echoTailUntil?: number;
};

/** One socket per utterance, one microphone/AudioContext per active conversation. */
export class BrowserVoiceInput {
  private run: Run | null = null;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private hardware: Promise<void> | null = null;
  private generation = 0;

  constructor(private readonly emit: (event: VoiceEvent) => void) {}

  private async prepareHardware() {
    if (this.hardware) return this.hardware;
    const generation = this.generation;
    const current = () => generation === this.generation;
    const promise = (async () => {
      const context = new AudioContext({ sampleRate: 24000 });
      this.context = context;
      await context.resume();
      if (!current()) return;
      if (context.sampleRate !== 24000)
        throw new Error("Браузер не поддерживает аудио 24 кГц.");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      if (!current()) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
      await context.audioWorklet.addModule("/pcm-worklet.js");
    })();
    this.hardware = promise;
    return promise;
  }

  prepareListening(sessionId: string, pauseMs?: number): Promise<void> {
    if (this.run) return this.run.ready;
    let resolve!: () => void, reject!: (error: Error) => void;
    const ready = new Promise<void>((ok, no) => {
      resolve = ok;
      reject = no;
    });
    // Preparation can be cancelled before the runtime begins awaiting readiness.
    void ready.catch(() => {});
    const run: Run = {
      cancelled: false,
      sending: false,
      ready,
      resolve,
      reject,
      ring: new NearEndBuffer(() => voiceTiming("input.echo_rejected")),
    };
    this.run = run;
    voiceTiming("input.prewarm");
    this.emit({ type: "preparing" });
    run.deadline = setTimeout(
      () => this.fail(run, "Превышено время подготовки микрофона."),
      30_000,
    );
    void (async () => {
      await this.prepareHardware();
      if (run.cancelled || !this.stream || !this.context) return;
      const context = this.context;
      const ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/voice`,
      );
      run.ws = ws;
      const node = new AudioWorkletNode(context, "pcm-capture");
      run.node = node;
      run.source = context.createMediaStreamSource(this.stream);
      run.source.connect(node);
      run.mute = context.createGain();
      run.mute.gain.value = 0;
      node.connect(run.mute).connect(context.destination);
      node.port.onmessage = ({ data }) => {
        if (run.cancelled) return;
        if (data === "flushed") {
          run.sending = false;
          if (ws.readyState === WebSocket.OPEN)
            ws.send(JSON.stringify({ type: "finish" }));
        } else if (data instanceof ArrayBuffer) {
          if (run.sending) {
            if (performance.now() < (run.echoTailUntil ?? 0))
              this.send(run, run.ring.filter(data));
            else {
              run.ring.clear();
              this.send(run, data);
            }
          } else run.ring.push(data);
        }
      };
      ws.onopen = () => {
        if (!run.cancelled)
          ws.send(
            JSON.stringify({
              type: "start",
              session_id: sessionId,
              sample_rate: 24000,
              channels: 1,
              ...(pauseMs ? { pause_ms: pauseMs } : {}),
            }),
          );
      };
      ws.onerror = () => this.fail(run, "Не удалось подключиться к backend.");
      ws.onclose = () => {
        if (!run.cancelled)
          this.fail(run, "Соединение закрылось до получения результата.");
      };
      ws.onmessage = ({ data }) => {
        if (run.cancelled) return;
        const event = JSON.parse(data) as VoiceEvent;
        if (event.type === "ready") {
          clearTimeout(run.deadline);
          run.deadline = setTimeout(
            () => this.fail(run, "Превышено время голосовой сессии."),
            120_000,
          );
          voiceTiming("input.ready");
          this.emit({ type: "prepared", pause_ms: event.pause_ms });
          run.resolve();
        } else if (event.type === "committed") {
          run.sending = false;
          run.ring.clear();
          run.node?.disconnect();
          run.source?.disconnect();
          voiceTiming(
            "endpoint",
            typeof event.silence_ms === "number" ? event.silence_ms : undefined,
          );
        } else if (event.type === "speech.started") {
          voiceTiming("speech.start");
        } else if (event.type === "utterance.final" || event.type === "empty") {
          this.releaseRun(run);
        } else if (event.type === "error") {
          this.fail(run, String(event.message ?? "Ошибка распознавания."));
          return;
        }
        if (event.type === "utterance.final") {
          const recognition = event.recognition as
            Record<string, unknown> | undefined;
          const timing = event.timing as Record<string, unknown> | undefined;
          for (const [key, name] of [
            ["realtime_final_ms", "realtime.final"],
            ["bounded_final_ms", "bounded.final"],
            ["candidate_ready_ms", "candidate.ready"],
          ] as const) {
            const value = timing?.[key] ?? recognition?.[key];
            if (typeof value === "number") voiceTiming(name, value);
          }
        }
        this.emit(event);
      };
    })().catch((error) =>
      this.fail(
        run,
        error instanceof Error ? error.message : "Ошибка микрофона.",
      ),
    );
    return ready;
  }

  async startListening(sessionId: string, pauseMs?: number) {
    const ready = this.prepareListening(sessionId, pauseMs);
    const run = this.run!;
    await ready;
    if (run.cancelled) return;
    run.sending = true;
    // The last speaker samples can reach the worklet after onended. Keep only
    // the reference (not a growing mic buffer) for a bounded 300 ms echo tail.
    run.echoTailUntil = performance.now() + 300;
    const preroll = run.ring.take(true);
    voiceTiming(
      "input.preroll",
      preroll.reduce((sum, frame) => sum + frame.byteLength / 48, 0),
    );
    for (const frame of preroll) this.send(run, frame);
    voiceTiming("input.active");
    this.emit({ type: "listening" });
  }

  async playbackReference(blob: Blob) {
    const run = this.run;
    if (!run) return;
    try {
      await this.hardware;
      if (run.cancelled || !this.context) return;
      const decoded = await this.context.decodeAudioData(
        await blob.arrayBuffer(),
      );
      if (!run.cancelled) run.ring.setReference(decoded.getChannelData(0));
    } catch {
      /* Prewarm stays available; without reference, no pre-roll is promoted. */
    }
  }
  armNearEnd(seconds: number) {
    this.run?.ring.arm(seconds);
  }
  finish() {
    if (this.run?.sending) this.run.node?.port.postMessage("finish");
  }
  pauseListening() {
    if (this.run) this.releaseRun(this.run);
  }
  stopListening() {
    this.generation += 1;
    this.pauseListening();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    void this.context?.close().catch(() => {});
    this.context = null;
    this.hardware = null;
    this.emit({ type: "stopped" });
  }
  private send(run: Run, frame: ArrayBuffer) {
    if (!run.sending || run.cancelled || run.ws?.readyState !== WebSocket.OPEN)
      return;
    if (run.ws.bufferedAmount > 48000 * 3) {
      this.fail(run, "Сеть не успевает передавать аудио.");
      return;
    }
    run.ws.send(frame);
  }
  private releaseRun(run: Run) {
    run.cancelled = true;
    run.sending = false;
    run.ring.clear();
    clearTimeout(run.deadline);
    run.reject(new Error("Подготовка отменена."));
    run.node?.disconnect();
    run.source?.disconnect();
    run.mute?.disconnect();
    run.ws?.close();
    if (this.run === run) this.run = null;
  }
  private fail(run: Run, message: string) {
    if (run.cancelled) return;
    run.reject(new Error(message));
    this.stopListening();
    this.emit({ type: "error", message });
  }
}
