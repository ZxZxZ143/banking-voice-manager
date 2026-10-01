import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createConversationEvent } from '../src/events/ConversationEvent.ts';
import { InMemoryEventStore } from '../src/events/EventStore.ts';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';
import { HttpAgentClient, MockAgentClient } from '../src/services/agentClient.ts';
import { finalVoiceTranscript } from '../src/components/voice/voiceRuntimeBridge.ts';

const tts = { speak: async () => ({}), stop() {} };
const tick = () => new Promise(resolve => setImmediate(resolve));
const event = (id, session_id = 'a', channel = 'web') => createConversationEvent(
  { session_id, event_type: 'transcript.final', channel, text: 'Сәлем' },
  { id, timestamp: '2026-10-01T00:00:00.000Z' },
);

test('only web and phone are declared and accepted as channels', () => {
  const source = readFileSync(new URL('../src/channels/channel.ts', import.meta.url), 'utf8');
  const declared = source.match(/export type Channel = ([^;]+);/)[1]
    .split('|').map(value => value.trim().replaceAll("'", ''));
  assert.deepEqual(declared, ['web', 'phone']);
  assert.throws(() => new ConversationRuntime(new MockAgentClient(), tts,
    { channel: { channel: 'unsupported' } }), /Unsupported conversation channel/);
});

test('event factory supports minimal shape, explicit identity, and optional Agent data', () => {
  assert.deepEqual(event('1'), {
    id: '1', timestamp: '2026-10-01T00:00:00.000Z', session_id: 'a',
    event_type: 'transcript.final', channel: 'web', text: 'Сәлем',
  });
  const generated = createConversationEvent({ session_id: 'b', event_type: 'session.started', channel: 'phone' });
  assert.match(generated.id, /^[0-9a-f-]{36}$/);
  assert.equal(new Date(generated.timestamp).toISOString(), generated.timestamp);
  const rich = createConversationEvent({
    session_id: 'a', event_type: 'agent.response', channel: 'web', language: 'mixed',
    scenario: { scenario_id: 'SC01' }, action: ['lookup'], confidence: 0.8,
    conversation_status: 'awaiting_user', clarification: true, handoff: false,
    risk: { signals: [] }, latency: { router: 20 }, metadata: { mode: 'mock' },
  });
  assert.deepEqual(rich.risk, { signals: [] });
  assert.equal(rich.confidence, 0.8);
});

test('store filters sessions/channels/types and preserves insertion order on tied or older timestamps', () => {
  const store = new InMemoryEventStore();
  store.append(event('1'));
  store.append(event('2', 'b', 'phone'));
  store.append({ ...event('3'), timestamp: '2026-09-01T00:00:00.000Z' });
  assert.deepEqual(store.list().map(e => e.id), ['1', '2', '3']);
  assert.deepEqual(store.getBySession('a').map(e => e.id), ['1', '3']);
  assert.deepEqual(store.getBySession('missing'), []);
  assert.deepEqual(store.list({ channel: 'phone', event_type: 'transcript.final' }).map(e => e.id), ['2']);
  assert.deepEqual(store.list({ session_id: 'a', limit: 1 }).map(e => e.id), ['1']);
  assert.deepEqual(store.list({ limit: 0 }), []);
  assert.throws(() => store.list({ limit: -1 }));
});

test('store isolates appended/retrieved payloads and evicts oldest events at capacity', () => {
  const store = new InMemoryEventStore(2);
  const input = { ...event('1'), risk: { signals: ['original'] } };
  store.append(input);
  input.risk.signals.push('mutation');
  const result = store.list();
  result[0].risk.signals.push('another mutation');
  assert.deepEqual(store.list()[0].risk.signals, ['original']);
  store.append(event('2'));
  store.append(event('3'));
  assert.deepEqual(store.list().map(e => e.id), ['2', '3']);
  assert.throws(() => new InMemoryEventStore(0));
});

test('partial STT stays outside turns; final voice/text events preserve session/channel/metadata', async () => {
  const requests = [];
  const runtime = new ConversationRuntime({ sendMessage: async request => {
    requests.push(request);
    return { response_text: 'Ответ', conversation_status: 'awaiting_user' };
  } }, tts, { sessionId: 'incoming-call-session', channel: { channel: 'phone', metadata: { call_id: 'mock-call' } } });
  await runtime.startConversation();
  await runtime.startConversation();
  const partial = finalVoiceTranscript({ type: 'transcript.partial', text: 'часть' });
  if (partial) await runtime.handleTranscript(partial);
  assert.equal(requests.length, 0);
  assert.deepEqual(runtime.eventStore.list().map(e => e.event_type), ['session.started']);
  await runtime.handleTranscript(finalVoiceTranscript({
    type: 'utterance.final', text: '  Сәлем  ', language: 'kk', stt_after_commit_ms: 12,
  }));
  await runtime.sendText('Текст');
  const events = runtime.eventStore.getBySession('incoming-call-session');
  assert.deepEqual(events.map(e => e.event_type), [
    'session.started', 'transcript.final', 'agent.response', 'transcript.final', 'agent.response',
  ]);
  assert.equal(events[1].text, 'Сәлем');
  assert.equal(events[1].language, 'kk');
  assert.deepEqual(events[1].latency, { stt: 12 });
  assert.ok(events.every(e => e.channel === 'phone' && e.metadata.channel_metadata.call_id === 'mock-call'));
  assert.deepEqual(requests, [
    { session_id: 'incoming-call-session', text: 'Сәлем' },
    { session_id: 'incoming-call-session', text: 'Текст' },
  ]);
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
  runtime.dispose();
});

test('existing MockAgentClient emits web events with supplied scenario/confidence, without a risk requirement', async () => {
  const runtime = new ConversationRuntime(new MockAgentClient(), tts);
  await runtime.startConversation();
  await runtime.sendText('Вопрос');
  const events = runtime.eventStore.list();
  assert.ok(events.every(e => e.channel === 'web'));
  const selected = events.find(e => e.event_type === 'scenario.selected');
  assert.equal(selected.scenario.scenario_id, 'DEMO-SC01');
  assert.equal(selected.confidence, 0.92);
  assert.deepEqual(selected.latency, { router: 287, response: 170, total: 457 });
  assert.equal(events.find(e => e.event_type === 'agent.response').risk, undefined);
  runtime.dispose();
});

test('clarification and handoff reflect explicit Agent fields; terminal event precedes TTS completion', async () => {
  const responses = [
    { response_text: 'Уточните', conversation_status: 'awaiting_user', trace: { clarification: true } },
    { response_text: 'Другой вопрос?', conversation_status: 'awaiting_user', routing: { clarification_question: 'Другой вопрос?' } },
    { response_text: 'Ответ', conversation_status: 'awaiting_user', state: {}, trace: { clarification: false, handoff: false } },
    { response_text: 'Оператор', conversation_status: 'handoff', risk: { level: 'high', signals: [] } },
  ];
  let complete;
  const runtime = new ConversationRuntime({ sendMessage: async () => responses.shift() }, {
    speak: async text => text === 'Оператор' ? new Promise(resolve => { complete = resolve; }) : {}, stop() {},
  });
  await runtime.startConversation();
  await runtime.sendText('1');
  await runtime.sendText('2');
  await runtime.sendText('3');
  const finalTurn = runtime.sendText('4');
  await tick();
  assert.equal(runtime.getSnapshot().runtimeStatus, 'speaking');
  const clarifications = runtime.eventStore.list({ event_type: 'clarification.requested' });
  assert.deepEqual(clarifications.map(e => e.clarification), [true, 'Другой вопрос?']);
  const handoffs = runtime.eventStore.list({ event_type: 'handoff.requested' });
  assert.equal(handoffs.length, 1);
  assert.deepEqual(handoffs[0].risk, { level: 'high', signals: [] });
  assert.equal(runtime.eventStore.list().at(-1).event_type, 'conversation.ended');
  assert.equal(runtime.eventStore.list().at(-1).conversation_status, 'handoff');
  complete({});
  await finalTurn;
  runtime.dispose();
  assert.equal(runtime.eventStore.list({ event_type: 'conversation.ended' }).length, 1);
});

test('missing, null, malformed, or partial optional Agent payloads do not crash recording', async () => {
  for (const payload of [{}, { routing: null, state: null, trace: null, risk: null },
    { routing: { selections: [{ scenario_id: 'SC02', confidence: 0.5 }] }, trace: {} },
    { routing: { scenarios: [{ scenario_id: 'SC03', confidence: 0.6 }] } },
    { routing: 'partial', state: [], trace: { scenarios: 'partial', actions: null }, risk: { signals: [] } }]) {
    const response = { response_text: 'Ответ', conversation_status: 'active', ...payload };
    const runtime = new ConversationRuntime({ sendMessage: async () => response }, tts);
    await runtime.startConversation();
    await runtime.sendText('Вопрос');
    assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
    const recorded = runtime.eventStore.list({ event_type: 'agent.response' })[0];
    for (const key of ['risk', 'routing', 'state', 'trace']) assert.deepEqual(recorded[key], response[key]);
    runtime.dispose();
  }
});

test('throwing, rejecting, or pending logging cannot break or delay conversation or playback', async () => {
  for (const [append, fails] of [[() => { throw new Error('store failed'); }, true],
    [() => Promise.reject(new Error('store failed')), true], [() => new Promise(() => {}), false]]) {
    let spoken = 0;
    let reported = 0;
    const runtime = new ConversationRuntime(new MockAgentClient(), {
      speak: async () => { spoken += 1; return {}; }, stop() {},
    }, { eventStore: { append, getBySession: () => [], list: () => [] },
      onEventError: () => { reported += 1; throw new Error('diagnostics failed'); } });
    await runtime.startConversation();
    await runtime.sendText('Вопрос');
    await tick();
    assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
    assert.equal(runtime.getSnapshot().error, null);
    assert.equal(spoken, 1);
    if (fails) assert.ok(reported >= 3);
    else assert.equal(reported, 0);
    runtime.dispose();
  }
});

test('event sink mutation cannot change Agent data or reply language', async () => {
  const response = { response_text: 'Сәлем', conversation_status: 'active', state: { response_language: 'kk' } };
  let language;
  const runtime = new ConversationRuntime({ sendMessage: async () => response }, {
    speak: async (_text, value) => { language = value; return {}; }, stop() {},
  }, { eventStore: {
    append: event => { if (event.state) event.state.response_language = 'ru'; },
    getBySession: () => [], list: () => [],
  } });
  await runtime.startConversation();
  await runtime.sendText('Сәлем');
  assert.equal(language, 'kk');
  assert.equal(response.state.response_language, 'kk');
  runtime.dispose();
});

test('HTTP partial finance response preserves risk unchanged, and HTTP failure creates no Agent response event', async () => {
  const originalFetch = globalThis.fetch;
  const risk = { level: 'low', signals: [], recommended_action: null };
  let fail = false;
  globalThis.fetch = async (_url, options) => {
    assert.deepEqual(Object.keys(JSON.parse(options.body)).sort(), ['session_id', 'text']);
    return fail
      ? new Response(JSON.stringify({ detail: 'Unavailable' }), { status: 503 })
      : new Response(JSON.stringify({ response_text: 'Ответ', conversation_status: 'active', risk }));
  };
  const runtime = new ConversationRuntime(new HttpAgentClient('http://agent.example'), tts);
  try {
    await runtime.startConversation();
    await runtime.sendText('1');
    assert.deepEqual(runtime.eventStore.list({ event_type: 'agent.response' })[0].risk, risk);
    fail = true;
    await runtime.sendText('2');
    assert.match(runtime.getSnapshot().error, /503/);
    assert.equal(runtime.eventStore.list({ event_type: 'agent.response' }).length, 1);
    assert.equal(runtime.eventStore.list({ event_type: 'transcript.final' }).length, 2);
    await runtime.startConversation();
    assert.equal(runtime.eventStore.list({ event_type: 'session.started' }).length, 1);
  } finally {
    runtime.dispose();
    globalThis.fetch = originalFetch;
  }
});

test('reset closes old session, rejects stale response, and starts a distinct event stream', async () => {
  let resolve;
  const runtime = new ConversationRuntime({ sendMessage: () => new Promise(done => { resolve = done; }) }, tts);
  await runtime.startConversation();
  const oldSession = runtime.getSnapshot().sessionId;
  const turn = runtime.sendText('Старый вопрос');
  await tick();
  await runtime.resetConversation();
  resolve({ response_text: 'Поздний ответ', conversation_status: 'ended' });
  await turn;
  assert.deepEqual(runtime.eventStore.getBySession(oldSession).map(e => e.event_type), [
    'session.started', 'transcript.final', 'conversation.ended',
  ]);
  assert.equal(runtime.eventStore.getBySession(oldSession).at(-1).metadata.reason, 'reset');
  await runtime.startConversation();
  const newSession = runtime.getSnapshot().sessionId;
  assert.notEqual(newSession, oldSession);
  assert.deepEqual(runtime.eventStore.getBySession(newSession).map(e => e.event_type), ['session.started']);
  runtime.dispose();
});

test('local stop records once without changing Agent status; Agent ended is recorded even if TTS fails', async () => {
  const runtime = new ConversationRuntime(new MockAgentClient(), tts);
  await runtime.startConversation();
  await runtime.sendText('Вопрос');
  await runtime.endConversation();
  await runtime.endConversation();
  runtime.dispose();
  const ends = runtime.eventStore.list({ event_type: 'conversation.ended' });
  assert.equal(ends.length, 1);
  assert.equal(ends[0].metadata.reason, 'local_stop');
  assert.equal(ends[0].conversation_status, 'awaiting_user');
  assert.equal(runtime.getSnapshot().conversationStatus, 'awaiting_user');

  const ended = new ConversationRuntime({ sendMessage: async () => ({ response_text: 'Пока', conversation_status: 'ended' }) },
    { speak: async () => { throw new Error('TTS failed'); }, stop() {} });
  await ended.startConversation();
  await ended.sendText('Пока');
  assert.equal(ended.eventStore.list({ event_type: 'conversation.ended' })[0].metadata.reason, 'agent_status');
  assert.equal(ended.getSnapshot().runtimeStatus, 'error');
  ended.dispose();
});
