import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { BrowserTtsService, selectVoice } from '../src/services/tts/BrowserTtsService.ts';

const originalSynthesis = globalThis.speechSynthesis;
const originalUtterance = globalThis.SpeechSynthesisUtterance;

afterEach(() => {
  globalThis.speechSynthesis = originalSynthesis;
  globalThis.SpeechSynthesisUtterance = originalUtterance;
});

function installSpeech(voices = [{ name: 'Russian', lang: 'ru-RU', default: true }]) {
  const listeners = new Set();
  const synthesis = {
    voices,
    utterances: [],
    cancelCount: 0,
    getVoices() { return this.voices; },
    addEventListener(_name, callback) { listeners.add(callback); },
    removeEventListener(_name, callback) { listeners.delete(callback); },
    speak(utterance) { this.utterances.push(utterance); },
    cancel() { this.cancelCount += 1; },
    voicesChanged() { for (const listener of listeners) listener(); },
    get listenerCount() { return listeners.size; },
  };
  globalThis.speechSynthesis = synthesis;
  globalThis.SpeechSynthesisUtterance = class {
    constructor(text) { this.text = text; }
  };
  return synthesis;
}

const nextTick = () => new Promise((resolve) => setImmediate(resolve));

test('voice selection uses exact locale, prefix, then browser default', () => {
  const voices = [
    { name: 'Default', lang: 'en-US', default: true },
    { name: 'Russian prefix', lang: 'ru', default: false },
    { name: 'Kazakh exact', lang: 'kk-KZ', default: false },
  ];
  assert.equal(selectVoice(voices, 'kk').name, 'Kazakh exact');
  assert.equal(selectVoice(voices, 'ru').name, 'Russian prefix');
  assert.equal(selectVoice([voices[0]], 'kk').name, 'Default');
  assert.equal(selectVoice([], 'kk'), null);
});

test('speak resolves only on playback end and measures start/end events', async () => {
  const synthesis = installSpeech();
  const tts = new BrowserTtsService();
  let settled = false;
  const playback = tts.speak('Здравствуйте', 'ru').then((result) => {
    settled = true;
    return result;
  });
  await nextTick();
  const utterance = synthesis.utterances[0];
  assert.equal(utterance.lang, 'ru-RU');
  assert.equal(tts.lastSelectedVoice, 'Russian (ru-RU)');
  assert.equal(settled, false);
  utterance.onstart();
  await nextTick();
  assert.equal(settled, false);
  utterance.onend();
  const result = await playback;
  assert.equal(settled, true);
  assert.ok(result.firstAudioMs >= 0);
  assert.ok(result.totalMs >= result.firstAudioMs);
});

test('a second speak cancels the first and stop settles the second', async () => {
  const synthesis = installSpeech();
  const tts = new BrowserTtsService();
  const first = tts.speak('First', 'ru');
  await nextTick();
  const second = tts.speak('Second', 'ru');
  await assert.rejects(first, { name: 'AbortError' });
  await nextTick();
  assert.equal(synthesis.cancelCount, 1);
  assert.equal(synthesis.utterances.length, 2);
  assert.equal(synthesis.utterances[0].onstart, null);
  tts.stop();
  await assert.rejects(second, { name: 'AbortError' });
  assert.equal(synthesis.cancelCount, 2);
  tts.stop();
  const third = tts.speak('Third', 'ru');
  await nextTick();
  synthesis.utterances[2].onstart();
  synthesis.utterances[2].onend();
  await third;
});

test('empty text and unavailable synthesis reject without fake playback', async () => {
  const synthesis = installSpeech();
  const tts = new BrowserTtsService();
  await assert.rejects(tts.speak('   '), /empty/);
  assert.equal(synthesis.utterances.length, 0);
  globalThis.speechSynthesis = undefined;
  await assert.rejects(tts.speak('Hello'), /unavailable/);
});

test('voiceschanged selects a late Kazakh voice; cancellation while waiting settles', async () => {
  const synthesis = installSpeech([]);
  const tts = new BrowserTtsService();
  const waiting = tts.speak('Сәлеметсіз бе', 'kk');
  synthesis.voices = [{ name: 'Kazakh', lang: 'kk-KZ', default: false }];
  synthesis.voicesChanged();
  await nextTick();
  assert.equal(synthesis.utterances[0].voice.name, 'Kazakh');
  synthesis.utterances[0].onstart();
  synthesis.utterances[0].onend();
  await waiting;
  assert.equal(synthesis.listenerCount, 0);

  synthesis.voices = [];
  const cancelled = tts.speak('Waiting', 'kk');
  tts.stop();
  await assert.rejects(cancelled, { name: 'AbortError' });
  assert.equal(synthesis.listenerCount, 0);
});
