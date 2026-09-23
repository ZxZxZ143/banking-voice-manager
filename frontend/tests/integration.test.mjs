import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createTraceViewModel } from '../src/components/trace/traceViewModel.ts';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';
import { HttpAgentClient } from '../src/services/agentClient.ts';
import { createVoiceInputController, finalVoiceTranscript } from '../src/components/voice/voiceRuntimeBridge.ts';

const nextTick = () => new Promise((resolve) => setImmediate(resolve));

test('final STT events use the HTTP contract and reply language, keeping one session until ended', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  const voiceSessions = [];
  const spoken = [];
  const responses = [
    { response_text: 'Кеңсе Астанада.', conversation_status: 'active',
      state: { response_language: 'kk' }, routing: { response_language: 'ru' } },
    { response_text: 'Подтвердите запрос.', conversation_status: 'awaiting_confirmation',
      state: { response_language: null }, routing: { response_language: 'ru' } },
    { response_text: 'Сау болыңыз.', conversation_status: 'ended',
      state: { response_language: 'kk' } },
  ];
  globalThis.fetch = async (url, options) => {
    assert.equal(url, 'http://agent.example/api/message');
    const body = JSON.parse(options.body);
    assert.deepEqual(Object.keys(body).sort(), ['session_id', 'text']);
    requests.push(body);
    return new Response(JSON.stringify(responses[requests.length - 1]), {
      headers: { 'Content-Type': 'application/json' },
    });
  };
  const runtime = new ConversationRuntime(new HttpAgentClient('http://agent.example'), {
    speak: async (text, language) => { spoken.push({ text, language }); return { firstAudioMs: 5 }; },
    stop() {},
  });
  runtime.attachVoiceInput(createVoiceInputController(runtime, () => ({
    startListening: (sessionId) => { voiceSessions.push(sessionId); },
    stopListening() {},
  })));
  try {
    await runtime.startConversation();
    assert.equal(finalVoiceTranscript({ type: 'transcript.partial', text: 'partial' }), null);
    for (let index = 0; index < responses.length; index += 1) {
      await runtime.handleTranscript(finalVoiceTranscript({
        type: 'utterance.final', text: `request ${index}`, language: index === 0 ? 'ru' : null,
        stt_after_commit_ms: 120,
      }));
      assert.equal(runtime.getSnapshot().runtimeStatus, index === 2 ? 'ended' : 'listening');
    }
    assert.equal(requests.length, 3);
    assert.equal(voiceSessions.length, 3);
    assert.equal(new Set([...voiceSessions, ...requests.map((request) => request.session_id)]).size, 1);
    assert.deepEqual(spoken.map((item) => item.language), ['kk', 'ru', 'kk']);
    await runtime.handleTranscript({ text: 'late transcript' });
    assert.equal(requests.length, 3);
  } finally {
    runtime.dispose();
    globalThis.fetch = originalFetch;
  }
});

test('voice boundary carries language and timing through two turns, then stops on handoff', async () => {
  const requests = [];
  const spoken = [];
  const finishSpeech = [];
  let starts = 0;
  let stops = 0;
  const runtime = new ConversationRuntime(
    { sendMessage: async (request) => {
      requests.push(request);
      return requests.length === 1
        ? {
          response_text: 'Первый ответ', conversation_status: 'awaiting_user',
          trace: { transcript: request.text, latency_ms: { stt: 310, router: 287 } },
        }
        : {
          response_text: 'Передаю оператору', conversation_status: 'handoff',
          trace: { transcript: request.text, latency_ms: { router: 150 } },
        };
    } },
    {
      speak: (text, language) => {
        spoken.push({ text, language });
        return new Promise((resolve) => { finishSpeech.push(resolve); });
      },
      stop() {},
    },
  );
  runtime.attachVoiceInput({
    startListening: async () => { starts += 1; },
    stopListening: async () => { stops += 1; },
  });

  await runtime.startConversation();
  const first = runtime.handleTranscript({ text: 'Первый запрос', language: 'mixed', stt_ms: 444 });
  await runtime.handleTranscript({ text: 'Дубликат', language: 'ru' });
  await nextTick();
  assert.equal(requests.length, 1);
  assert.equal(runtime.getSnapshot().runtimeStatus, 'speaking');
  assert.equal(starts, 1);
  assert.equal(stops, 1);
  finishSpeech.shift()({ firstAudioMs: 50, totalMs: 300 });
  await first;
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
  assert.equal(starts, 2);
  const firstView = createTraceViewModel(runtime.getSnapshot());
  assert.equal(firstView.latency.find((item) => item.label === 'STT').value, '310 ms');
  assert.equal(firstView.latency.find((item) => item.label === 'STT').source, 'agent');
  assert.equal(firstView.latency.find((item) => item.label === 'TTS first audio').value, '50 ms');
  assert.equal(firstView.latency.find((item) => item.label === 'TTS first audio').source, 'browser');

  const second = runtime.handleTranscript({ text: 'Екінші сұрақ', language: 'kk', stt_ms: 180 });
  await nextTick();
  finishSpeech.shift()({ firstAudioMs: 40, totalMs: 250 });
  await second;
  assert.equal(runtime.getSnapshot().runtimeStatus, 'handoff');
  assert.equal(starts, 2);
  assert.equal(stops, 2);
  assert.equal(requests[0].session_id, requests[1].session_id);
  assert.deepEqual(spoken.map((item) => item.language), ['mixed', 'kk']);
  assert.equal(createTraceViewModel(runtime.getSnapshot()).latency.find((item) => item.label === 'STT').value, '180 ms');
  runtime.dispose();
});
