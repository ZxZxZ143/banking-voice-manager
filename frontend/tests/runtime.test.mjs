import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';
import { HttpAgentClient } from '../src/services/agentClient.ts';

test('two turns reuse the session and listening resumes only after playback', async () => {
  const requests = [];
  const starts = [];
  let finishPlayback;
  const runtime = new ConversationRuntime(
    { sendMessage: async (request) => {
      requests.push(request);
      return { response_text: 'Ответ', conversation_status: 'awaiting_user' };
    } },
    { speak: () => new Promise((resolve) => { finishPlayback = resolve; }), stop() {} },
  );
  runtime.attachVoiceInput({ startListening: () => { starts.push('start'); }, stopListening() {} });

  await runtime.startConversation();
  const first = runtime.handleTranscript({ text: 'Первый вопрос', language: 'ru', stt_ms: 42 });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(runtime.getSnapshot().runtimeStatus, 'speaking');
  assert.equal(runtime.getSnapshot().sttLatencyMs, 42);
  assert.equal(starts.length, 1);
  finishPlayback({ firstAudioMs: 3, totalMs: 5 });
  await first;
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
  assert.equal(runtime.getSnapshot().ttsFirstAudioMs, 3);
  assert.equal(starts.length, 2);

  const second = runtime.sendText('Второй вопрос');
  await new Promise((resolve) => setImmediate(resolve));
  finishPlayback({});
  await second;
  assert.equal(runtime.getSnapshot().ttsFirstAudioMs, null);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].session_id, requests[1].session_id);
  assert.deepEqual(requests.map((request) => request.text), ['Первый вопрос', 'Второй вопрос']);
  assert.equal(runtime.getSnapshot().messages.length, 4);
  runtime.dispose();
});

test('terminal response does not resume listening, and backend failure stays visible', async () => {
  let starts = 0;
  const runtime = new ConversationRuntime(
    { sendMessage: async () => ({ response_text: 'Передаю оператору', conversation_status: 'handoff' }) },
    { speak: async () => ({}), stop() {} },
  );
  runtime.attachVoiceInput({ startListening: () => { starts += 1; }, stopListening() {} });
  await runtime.startConversation();
  await runtime.sendText('Оператор');
  assert.equal(runtime.getSnapshot().runtimeStatus, 'handoff');
  assert.equal(starts, 1);
  runtime.dispose();

  const failing = new ConversationRuntime(
    { sendMessage: async () => { throw new Error('Agent API HTTP 503: unavailable'); } },
    { speak: async () => ({}), stop() {} },
  );
  await failing.startConversation();
  await failing.sendText('Вопрос');
  assert.equal(failing.getSnapshot().runtimeStatus, 'error');
  assert.match(failing.getSnapshot().error, /503/);
  assert.equal(failing.getSnapshot().messages.length, 1);
  failing.dispose();
});

test('TTS failure is shown and reset creates a new session', async () => {
  const runtime = new ConversationRuntime(
    { sendMessage: async () => ({ response_text: 'Ответ', conversation_status: 'awaiting_confirmation' }) },
    { speak: async () => { throw new Error('TTS unavailable'); }, stop() {} },
  );
  await runtime.startConversation();
  const oldSessionId = runtime.getSnapshot().sessionId;
  await runtime.sendText('Подтверждение');
  assert.equal(runtime.getSnapshot().runtimeStatus, 'error');
  assert.match(runtime.getSnapshot().error, /TTS unavailable/);
  assert.equal(runtime.getSnapshot().messages.length, 2);
  await runtime.resetConversation();
  assert.equal(runtime.getSnapshot().runtimeStatus, 'idle');
  assert.equal(runtime.getSnapshot().messages.length, 0);
  assert.notEqual(runtime.getSnapshot().sessionId, oldSessionId);
  runtime.dispose();
});

test('HTTP client rejects malformed replies and surfaces backend errors', async () => {
  const originalFetch = globalThis.fetch;
  const client = new HttpAgentClient('http://localhost:8000');
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ response_text: 'Missing status' }), {
      headers: { 'Content-Type': 'application/json' },
    });
    await assert.rejects(client.sendMessage({ session_id: 'session', text: 'Hello' }), /Malformed/);

    globalThis.fetch = async () => new Response(JSON.stringify({
      error: { code: 'unavailable', message: 'Agent is offline' },
    }), { status: 503, headers: { 'Content-Type': 'application/json' } });
    await assert.rejects(client.sendMessage({ session_id: 'session', text: 'Hello' }), /503: Agent is offline/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
