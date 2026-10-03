import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { BackendTtsService } from "../src/services/tts/BackendTtsService.ts";
import {
  selectVoice,
  BrowserTtsService,
} from "../src/services/tts/BrowserTtsService.ts";

const originals = {
  fetch: globalThis.fetch,
  Audio: globalThis.Audio,
  create: URL.createObjectURL,
  revoke: URL.revokeObjectURL,
};
afterEach(() => {
  globalThis.fetch = originals.fetch;
  globalThis.Audio = originals.Audio;
  URL.createObjectURL = originals.create;
  URL.revokeObjectURL = originals.revoke;
});
const tick = () => new Promise((resolve) => setImmediate(resolve));
function setup() {
  const calls = [],
    sounds = [],
    revoked = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(options);
    return {
      ok: true,
      headers: { get: () => "audio/mpeg" },
      blob: async () => new Blob(["fixture"], { type: "audio/mpeg" }),
    };
  };
  URL.createObjectURL = () => "blob:fixture";
  URL.revokeObjectURL = (url) => revoked.push(url);
  globalThis.Audio = class {
    constructor() {
      sounds.push(this);
    }
    play() {
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
    removeAttribute() {}
    load() {}
  };
  const fallback = {
    calls: [],
    stop() {},
    async speak(text, language) {
      this.calls.push({ text, language });
      return { firstAudioMs: 1, totalMs: 2 };
    },
    lastSelectedVoice: "fixture browser voice",
  };
  return { calls, sounds, revoked, fallback };
}

for (const language of ["ru", "kk"])
  test(`backend audio uses authorized ${language} and resolves after playback`, async () => {
    const { calls, sounds, revoked, fallback } = setup();
    const tts = new BackendTtsService(fallback);
    let settled = false;
    const pending = tts.speak("10,47%", language).then((value) => {
      settled = true;
      return value;
    });
    await tick();
    assert.deepEqual(JSON.parse(calls[0].body), { text: "10,47%", language });
    assert.equal(settled, false);
    sounds[0].onplaying();
    sounds[0].onended();
    const result = await pending;
    assert.ok(result.firstAudioMs >= 0);
    assert.ok(result.totalMs >= result.firstAudioMs);
    assert.equal(fallback.calls.length, 0);
    assert.deepEqual(revoked, ["blob:fixture"]);
  });

test("backend unavailable uses browser fallback with the same language", async () => {
  const { fallback } = setup();
  globalThis.fetch = async () => new Response("", { status: 503 });
  const tts = new BackendTtsService(fallback);
  await tts.speak("Сәлем", "kk");
  assert.deepEqual(fallback.calls, [{ text: "Сәлем", language: "kk" }]);
  assert.match(tts.lastSelectedVoice, /Browser fallback/);
});

test("request timeout falls back; explicit cancellation never starts fallback", async () => {
  const { fallback } = setup();
  globalThis.fetch = (_url, { signal }) =>
    new Promise((_resolve, reject) =>
      signal.addEventListener("abort", () =>
        reject(new DOMException("aborted", "AbortError")),
      ),
    );
  const tts = new BackendTtsService(fallback, "/api/speech/tts", 5);
  await tts.speak("Проверка", "ru");
  assert.equal(fallback.calls.length, 1);
  const cancelled = tts.speak("Не произносить", "kk");
  tts.stop();
  await assert.rejects(cancelled, { name: "AbortError" });
  assert.equal(fallback.calls.length, 1);
});

test("playback cancellation revokes blob and never repeats through browser", async () => {
  const { fallback, sounds, revoked } = setup();
  const tts = new BackendTtsService(fallback);
  const pending = tts.speak("Проверка", "ru");
  await tick();
  sounds[0].onplaying();
  tts.stop();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(sounds[0].paused, true);
  assert.deepEqual(revoked, ["blob:fixture"]);
  assert.equal(fallback.calls.length, 0);
});

test("a partly spoken backend error never repeats speech", async () => {
  const { fallback, sounds } = setup();
  const tts = new BackendTtsService(fallback);
  const pending = tts.speak("Предупреждение", "ru");
  await tick();
  sounds[0].onplaying();
  sounds[0].onerror();
  await assert.rejects(pending, /playback failed/);
  assert.equal(fallback.calls.length, 0);
});

test("malformed audio falls back without assigning untrusted URL", async () => {
  const { fallback, sounds } = setup();
  globalThis.fetch = async () =>
    new Response("text", { headers: { "Content-Type": "text/html" } });
  await new BackendTtsService(fallback).speak("Проверка", "ru");
  assert.equal(sounds.length, 0);
  assert.equal(fallback.calls.length, 1);
});

test("browser prefers natural voices only within requested locale", () => {
  const voices = [
    { name: "English Natural", lang: "en-US", default: true },
    { name: "RU regular", lang: "ru-RU" },
    { name: "RU Neural", lang: "ru-RU" },
    { name: "KK regular", lang: "kk-KZ" },
    { name: "KK Online", lang: "kk-KZ" },
  ];
  assert.equal(selectVoice(voices, "ru").name, "RU Neural");
  assert.equal(selectVoice(voices, "kk").name, "KK Online");
});

test("browser keeps a chosen locale voice across reordered voice lists and conservative prosody", async () => {
  const previous = {
    speechSynthesis: globalThis.speechSynthesis,
    SpeechSynthesisUtterance: globalThis.SpeechSynthesisUtterance,
  };
  try {
    const voices = [
      { name: "RU Natural", lang: "ru-RU" },
      { name: "Russian", lang: "ru-RU" },
    ];
    const utterances = [];
    globalThis.speechSynthesis = {
      getVoices: () => voices,
      speak: (u) => utterances.push(u),
      cancel() {},
    };
    globalThis.SpeechSynthesisUtterance = class {
      constructor(text) {
        this.text = text;
      }
    };
    const tts = new BrowserTtsService();
    for (let i = 0; i < 2; i++) {
      const pending = tts.speak("Проверка", "ru");
      await tick();
      const u = utterances[i];
      assert.equal(u.voice.name, "RU Natural");
      assert.equal(u.lang, "ru-RU");
      assert.equal(u.rate, 0.97);
      assert.equal(u.pitch, 1);
      assert.equal(u.volume, 1);
      u.onstart();
      u.onend();
      await pending;
      voices.reverse();
    }
  } finally {
    Object.assign(globalThis, previous);
  }
});

test("missing locale is not cached over a matching voice installed later", async () => {
  const previous = {
    speechSynthesis: globalThis.speechSynthesis,
    SpeechSynthesisUtterance: globalThis.SpeechSynthesisUtterance,
  };
  try {
    const voices = [{ name: "Russian", lang: "ru-RU", default: true }];
    const utterances = [];
    globalThis.speechSynthesis = {
      getVoices: () => voices,
      speak: (u) => utterances.push(u),
      cancel() {},
    };
    globalThis.SpeechSynthesisUtterance = class {};
    const tts = new BrowserTtsService();
    for (let i = 0; i < 2; i++) {
      const pending = tts.speak("Сәлем", "kk");
      await tick();
      const u = utterances[i];
      assert.equal(u.lang, "kk-KZ");
      if (i === 0) {
        assert.equal(u.voice, undefined);
        assert.match(tts.lastSelectedVoice, /matching voice unavailable/);
      } else assert.equal(u.voice.name, "Kazakh Natural");
      u.onstart();
      u.onend();
      await pending;
      voices.push({ name: "Kazakh Natural", lang: "kk-KZ" });
    }
  } finally {
    Object.assign(globalThis, previous);
  }
});
