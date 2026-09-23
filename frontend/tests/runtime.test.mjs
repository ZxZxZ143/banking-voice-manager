import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';
import { HttpAgentClient } from '../src/services/agentClient.ts';
import { createTraceViewModel } from '../src/components/trace/traceViewModel.ts';

test('text-only toggle stops capture, rejects late voice finals, and keeps the session', async () => {
  const requests = [];
  let starts = 0;
  let stops = 0;
  const runtime = new ConversationRuntime(
    { sendMessage: async (request) => {
      requests.push(request);
      return { response_text: 'Ответ', conversation_status: 'awaiting_user' };
    } },
    { speak: async () => ({}), stop() {} },
  );
  runtime.attachVoiceInput({ startListening: () => { starts += 1; }, stopListening: () => { stops += 1; } });
  assert.equal(runtime.getSnapshot().voiceInputEnabled, true);
  await runtime.startConversation();
  const session = runtime.getSnapshot().sessionId;
  await runtime.setVoiceInputEnabled(false);
  assert.equal(stops, 1);
  await runtime.handleTranscript({ text: 'Поздняя речь из комнаты' });
  assert.equal(requests.length, 0);
  await runtime.sendText('Текстовый вопрос');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].session_id, session);
  assert.equal(runtime.getSnapshot().sessionId, session);
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
  assert.equal(runtime.getSnapshot().conversationStatus, 'awaiting_user');
  assert.equal(starts, 1);
  await runtime.setVoiceInputEnabled(true);
  assert.equal(starts, 2);
  assert.equal(runtime.getSnapshot().sessionId, session);
  runtime.dispose();
});

test('text-only before start and during TTS prevents automatic microphone resume', async () => {
  let starts = 0;
  let finishPlayback;
  const runtime = new ConversationRuntime(
    { sendMessage: async () => ({ response_text: 'Ответ', conversation_status: 'active' }) },
    { speak: () => new Promise(resolve => { finishPlayback = resolve; }), stop() {} },
  );
  runtime.attachVoiceInput({ startListening: () => { starts += 1; }, stopListening() {} });
  await runtime.setVoiceInputEnabled(false);
  await runtime.startConversation();
  assert.equal(starts, 0);
  await runtime.setVoiceInputEnabled(true);
  assert.equal(starts, 1);
  const turn = runtime.sendText('Вопрос');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.getSnapshot().runtimeStatus, 'speaking');
  await runtime.setVoiceInputEnabled(false);
  finishPlayback({});
  await turn;
  assert.equal(starts, 1);
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
  await runtime.resetConversation();
  assert.equal(runtime.getSnapshot().voiceInputEnabled, false);
  runtime.dispose();
});

test('local stop preserves the last backend status and supervisor trace', async () => {
  let voiceStops = 0;
  let playbackStops = 0;
  const response = {
    response_text: 'Что именно вы хотите уточнить?',
    conversation_status: 'awaiting_user',
    state: { conversation_status: 'awaiting_user' },
    trace: { scenarios: [{ scenario_id: 'SYS_UNCLEAR' }] },
  };
  const runtime = new ConversationRuntime(
    { sendMessage: async () => response },
    { speak: async () => ({}), stop: () => { playbackStops += 1; } },
  );
  runtime.attachVoiceInput({ startListening() {}, stopListening: () => { voiceStops += 1; } });
  await runtime.startConversation();
  assert.equal(runtime.getSnapshot().conversationStatus, null);
  await runtime.sendText('У меня вопрос');
  const before = runtime.getSnapshot();
  await runtime.endConversation();
  const after = runtime.getSnapshot();
  assert.equal(after.runtimeStatus, 'ended');
  assert.equal(after.conversationStatus, 'awaiting_user');
  assert.equal(after.lastResponse, before.lastResponse);
  assert.equal(after.latestState, before.latestState);
  assert.equal(after.latestTrace, before.latestTrace);
  assert.equal(createTraceViewModel(after).conversationStatus, 'awaiting_user');
  assert.equal(voiceStops, 2);
  assert.equal(playbackStops, 1);
  runtime.dispose();
});

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

    globalThis.fetch = async () => new Response(JSON.stringify({
      response_text: '  ', conversation_status: 'awaiting_user',
    }), { headers: { 'Content-Type': 'application/json' } });
    await assert.rejects(client.sendMessage({ session_id: 'session', text: 'Hello' }), /Malformed/);

    globalThis.fetch = async () => new Response(JSON.stringify({
      response_text: 'Valid', conversation_status: 'active', extra_field: 'accepted',
    }), { headers: { 'Content-Type': 'application/json' } });
    assert.equal((await client.sendMessage({ session_id: 'session', text: 'Hello' })).response_text, 'Valid');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('reset waits for a delayed voice start before stopping it', async () => {
  let releaseStart;
  let starts = 0;
  let stops = 0;
  const runtime = new ConversationRuntime(
    { sendMessage: async () => ({ response_text: 'Ответ', conversation_status: 'active' }) },
    { speak: async () => ({}), stop() {} },
  );
  runtime.attachVoiceInput({
    startListening: () => {
      starts += 1;
      return starts === 1 ? new Promise((resolve) => { releaseStart = resolve; }) : undefined;
    },
    stopListening: () => { stops += 1; },
  });
  const starting = runtime.startConversation();
  await new Promise((resolve) => setImmediate(resolve));
  const oldSession = runtime.getSnapshot().sessionId;
  const resetting = runtime.resetConversation();
  assert.equal(stops, 0);
  releaseStart();
  await Promise.all([starting, resetting]);
  assert.equal(stops, 1);
  assert.equal(runtime.getSnapshot().runtimeStatus, 'idle');
  assert.notEqual(runtime.getSnapshot().sessionId, oldSession);
  await runtime.startConversation();
  assert.equal(starts, 2);
  runtime.dispose();
});

test('reset prevents an old agent response from changing the new session', async () => {
  let finishAgent;
  let stops = 0;
  const runtime = new ConversationRuntime(
    { sendMessage: () => new Promise((resolve) => { finishAgent = resolve; }) },
    { speak: async () => ({}), stop: () => { stops += 1; } },
  );
  await runtime.startConversation();
  const oldTurn = runtime.sendText('Старый вопрос');
  await new Promise((resolve) => setImmediate(resolve));
  await runtime.resetConversation();
  finishAgent({ response_text: 'Поздний ответ', conversation_status: 'active' });
  await oldTurn;
  assert.equal(stops, 1);
  assert.equal(runtime.getSnapshot().messages.length, 0);
  assert.equal(runtime.getSnapshot().runtimeStatus, 'idle');
  runtime.dispose();
});

test('reset cancels pending playback and ignores its late rejection', async () => {
  let cancelPlayback;
  let stops = 0;
  const runtime = new ConversationRuntime(
    { sendMessage: async () => ({ response_text: 'Ответ', conversation_status: 'active' }) },
    {
      speak: () => new Promise((_resolve, reject) => {
        cancelPlayback = () => reject(new DOMException('Cancelled', 'AbortError'));
      }),
      stop: () => { stops += 1; cancelPlayback?.(); },
    },
  );
  await runtime.startConversation();
  const turn = runtime.sendText('Вопрос');
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(runtime.getSnapshot().runtimeStatus, 'speaking');
  await runtime.resetConversation();
  await turn;
  assert.equal(stops, 1);
  assert.equal(runtime.getSnapshot().runtimeStatus, 'idle');
  assert.equal(runtime.getSnapshot().messages.length, 0);
  runtime.dispose();
});

test('HTTP client reports a timeout while reading the response body', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, { signal }) => ({
      ok: true,
      json: () => new Promise((_resolve, reject) => {
        if (signal.aborted) reject(signal.reason);
        else signal.addEventListener('abort', () => reject(signal.reason), { once: true });
      }),
    });
    const client = new HttpAgentClient('http://localhost:8000', 5);
    const keepEventLoopAlive = new Promise((resolve) => setTimeout(resolve, 30));
    await assert.rejects(client.sendMessage({ session_id: 'session', text: 'Hello' }), /timed out/);
    await keepEventLoopAlive;
  } finally {
    globalThis.fetch = originalFetch;
  }
});
