import assert from "node:assert/strict";
import { test } from "node:test";
import { NearEndBuffer } from "../src/components/voice/NearEndBuffer.ts";
import { BrowserVoiceInput } from "../src/components/voice/BrowserVoiceInput.ts";
import { ConversationRuntime } from "../src/runtime/ConversationRuntime.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));
function wave(hz, seconds = 2) {
  return Float32Array.from(
    { length: 24000 * seconds },
    (_, i) => 0.2 * Math.sin((i * 2 * Math.PI * hz) / 24000),
  );
}
function pcm(samples) {
  return Int16Array.from(samples, (value) => Math.round(value * 32767)).buffer;
}

test("near-end buffer preserves first phoneme and bounds retained audio to 400 ms", () => {
  const ring = new NearEndBuffer();
  ring.setReference(wave(300));
  ring.arm(1, 0);
  const caller = wave(733);
  for (let n = 0; n < 7; n++)
    ring.push(pcm(caller.slice(n * 2400, (n + 1) * 2400)), n * 100);
  const frames = ring.take();
  assert.equal(frames.length, 4);
  assert.deepEqual(frames[0], pcm(caller.slice(3 * 2400, 4 * 2400)));
  assert.equal(
    frames.reduce((sum, frame) => sum + frame.byteLength, 0),
    ring.maxBytes,
  );
  assert.deepEqual(ring.take(), []);
});

test("speaker echo, silence and unreferenced pre-roll cannot become a turn", () => {
  const reference = wave(300);
  for (const mode of ["echo", "delayed_echo", "silence", "unreferenced"]) {
    const ring = new NearEndBuffer();
    if (mode !== "unreferenced") ring.setReference(reference);
    ring.arm(1, 0);
    const end = mode === "delayed_echo" ? 0.95 : 1;
    const frame =
      mode === "silence"
        ? new ArrayBuffer(4800)
        : pcm(reference.slice(end * 24000 - 2400, end * 24000));
    ring.push(frame, 0);
    assert.deepEqual(ring.take(), [], mode);
  }
});

test("speaker tail after playback ends is rejected while independent first speech survives", () => {
  const ring = new NearEndBuffer();
  const reference = wave(300);
  ring.setReference(reference);
  ring.arm(1.9, 0);
  ring.take(true);
  const echo = pcm(reference.slice(45600, 48000));
  assert.ok(
    new Int16Array(ring.filter(echo, 150)).every((sample) => sample === 0),
  );
  const caller = pcm(wave(733).slice(0, 2400));
  assert.deepEqual(ring.filter(caller, 150), caller);
});

test("prewarm sends no PCM, reuses hardware, and releases every track on stop", async (t) => {
  const sockets = [],
    nodes = [],
    tracks = [],
    events = [];
  let permissions = 0;
  const original = Object.fromEntries(
    [
      "navigator",
      "AudioContext",
      "AudioWorkletNode",
      "WebSocket",
      "location",
    ].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  t.after(() => {
    for (const [key, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      mediaDevices: {
        getUserMedia: async (constraints) => {
          permissions++;
          assert.equal(constraints.audio.echoCancellation, true);
          assert.equal(constraints.audio.noiseSuppression, true);
          const track = {
            stopped: false,
            stop() {
              this.stopped = true;
            },
          };
          tracks.push(track);
          return { getTracks: () => [track] };
        },
      },
    },
  });
  globalThis.location = { protocol: "http:", host: "fixture" };
  const connection = () => ({
    connect() {
      return this;
    },
    disconnect() {},
  });
  globalThis.AudioContext = class {
    sampleRate = 24000;
    audioWorklet = { addModule: async () => {} };
    destination = {};
    async resume() {}
    async close() {}
    createMediaStreamSource() {
      return connection();
    }
    createGain() {
      return { ...connection(), gain: { value: 1 } };
    }
    async decodeAudioData() {
      return { getChannelData: () => wave(300) };
    }
  };
  globalThis.AudioWorkletNode = class {
    port = {};
    connect() {
      return connection();
    }
    disconnect() {}
    constructor() {
      nodes.push(this);
    }
  };
  globalThis.WebSocket = class {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    sent = [];
    constructor() {
      sockets.push(this);
    }
    send(frame) {
      this.sent.push(frame);
    }
    close() {
      this.readyState = 3;
      this.onclose?.();
    }
  };
  const input = new BrowserVoiceInput((event) => events.push(event));
  t.after(() => input.stopListening());
  const ready = input.prepareListening("fixture");
  await tick();
  sockets[0].onopen();
  sockets[0].onmessage({ data: JSON.stringify({ type: "ready" }) });
  await ready;
  nodes[0].port.onmessage({ data: pcm(wave(733).slice(0, 2400)) });
  assert.equal(
    sockets[0].sent.filter((value) => value instanceof ArrayBuffer).length,
    0,
  );
  await input.playbackReference(new Blob(["fixture"]));
  input.armNearEnd(1);
  const beginning = pcm(wave(733).slice(0, 2400));
  nodes[0].port.onmessage({ data: beginning });
  assert.equal(
    sockets[0].sent.filter((value) => value instanceof ArrayBuffer).length,
    0,
  );
  await input.startListening("fixture");
  assert.deepEqual(
    sockets[0].sent.find((value) => value instanceof ArrayBuffer),
    beginning,
  );
  input.pauseListening();
  assert.equal(tracks[0].stopped, false);
  const second = input.prepareListening("fixture");
  await tick();
  sockets[1].onopen();
  sockets[1].onmessage({ data: JSON.stringify({ type: "ready" }) });
  await second;
  assert.equal(permissions, 1);
  input.stopListening();
  assert.ok(tracks.every((track) => track.stopped));
  assert.ok(sockets.every((socket) => socket.readyState === 3));
  let permit;
  navigator.mediaDevices.getUserMedia = () =>
    new Promise((resolve) => {
      permit = resolve;
    });
  const late = input.prepareListening("cancelled-before-permission");
  await tick();
  input.stopListening();
  const lateTrack = {
    stopped: false,
    stop() {
      this.stopped = true;
    },
  };
  permit({ getTracks: () => [lateTrack] });
  await tick();
  await assert.rejects(late);
  assert.equal(
    lateTrack.stopped,
    true,
    "late permission must not leave hardware active",
  );
});

test("runtime prepares during TTS, activates after end and fully stops on terminal/reset", async () => {
  const calls = [];
  let endPlayback,
    status = "awaiting_user";
  const runtime = new ConversationRuntime(
    {
      sendMessage: async () => ({
        response_text: "Ответ",
        conversation_status: status,
      }),
    },
    {
      speak: () =>
        new Promise((resolve) => {
          endPlayback = resolve;
        }),
      stop() {},
    },
  );
  runtime.attachVoiceInput({
    prepareListening() {
      calls.push("prepare");
    },
    startListening() {
      calls.push("active");
    },
    pauseListening() {
      calls.push("pause");
    },
    stopListening() {
      calls.push("stop");
    },
  });
  await runtime.startConversation();
  const pending = runtime.sendText("Вопрос");
  await tick();
  assert.deepEqual(calls, ["active", "pause", "prepare"]);
  endPlayback({});
  await pending;
  assert.equal(calls.at(-1), "active");
  status = "handoff";
  const terminal = runtime.sendText("Оператор");
  await tick();
  assert.equal(calls.at(-1), "pause");
  endPlayback({});
  await terminal;
  assert.equal(calls.at(-1), "stop");
  assert.equal(runtime.getSnapshot().runtimeStatus, "handoff");
  await runtime.resetConversation();
  assert.equal(calls.at(-1), "stop");
  runtime.dispose();
});

for (const action of ["reset", "end", "disable", "dispose"]) {
  test(`${action} releases a prepared controller while its input handshake is still pending`, async () => {
    let rejectReady;
    let stopped = false;
    const runtime = new ConversationRuntime(
      {
        sendMessage: async () => {
          throw new Error("No business call expected");
        },
      },
      { speak: async () => ({}), stop() {} },
    );
    runtime.attachVoiceInput({
      prepareListening() {},
      startListening() {
        return new Promise((_, reject) => {
          rejectReady = reject;
        });
      },
      stopListening() {
        stopped = true;
        rejectReady?.(new Error("Readiness cancelled"));
      },
    });
    const starting = runtime.startConversation();
    await tick();
    const stopping =
      action === "reset"
        ? runtime.resetConversation()
        : action === "end"
          ? runtime.endConversation()
          : action === "disable"
            ? runtime.setVoiceInputEnabled(false)
            : runtime.dispose();
    assert.equal(
      stopped,
      true,
      "must not queue stop behind the unresolved handshake",
    );
    await stopping;
    await starting;
    assert.equal(runtime.getSnapshot().error, null);
    runtime.dispose();
  });
}
