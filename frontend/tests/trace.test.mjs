import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  createTraceViewModel, formatConfidence, formatLatency,
} from '../src/components/trace/traceViewModel.ts';

const snapshot = (changes = {}) => ({
  sessionId: 'session', runtimeStatus: 'listening', conversationStatus: 'active',
  messages: [], lastResponse: null, error: null, latestTrace: null, latestState: null,
  sttLatencyMs: null, ttsFirstAudioMs: null,
  ...changes,
});

test('missing or partial trace produces a safe empty view', () => {
  const empty = createTraceViewModel(snapshot());
  assert.equal(empty.hasData, false);
  assert.deepEqual(empty.scenarios, []);
  assert.deepEqual(empty.latency, []);

  const partial = createTraceViewModel(snapshot({ latestTrace: { scenarios: [null, {}, { scenario_id: 'SC1' }] } }));
  assert.equal(partial.hasData, true);
  assert.deepEqual(partial.scenarios.map((item) => item.id), ['SC1']);
  assert.equal(partial.reason, null);
});

test('confidence and latency are formatting only', () => {
  assert.equal(formatConfidence(0.92), '92%');
  assert.equal(formatConfidence(1.3), null);
  assert.equal(formatLatency(310), '310 ms');
  assert.equal(formatLatency(1140), '1.14 s');
  assert.equal(formatLatency(-1), null);
});

test('multi-intent and state order follow the agent; backend latency wins', () => {
  const view = createTraceViewModel(snapshot({
    conversationStatus: 'awaiting_confirmation',
    sttLatencyMs: 500,
    ttsFirstAudioMs: 350,
    latestTrace: {
      scenarios: [
        { scenario_id: 'SC27', confidence: 0.9 },
        { scenario_id: 'SC04', confidence: 0.7 },
      ],
      alternatives: [{ scenario_id: 'SC23', confidence: 0.31 }],
      reason: 'Short application reason',
      latency_ms: { stt: 310, router: 287, total: 1140 },
    },
    latestState: {
      active_scenario: 'SC27', scenario_stack: ['SC04', 'SC18'], pending_scenarios: ['SC33'],
    },
  }));
  assert.deepEqual(view.scenarios.map((item) => item.id), ['SC27', 'SC04']);
  assert.deepEqual(view.scenarioStack.map((item) => item.id), ['SC04', 'SC18']);
  assert.equal(view.activeScenario.id, 'SC27');
  assert.equal(view.scenarios[0].confidence, '90%');
  assert.equal(view.latency.find((item) => item.label === 'STT').value, '310 ms');
  assert.equal(view.latency.find((item) => item.label === 'STT').source, 'agent');
  assert.equal(view.latency.find((item) => item.label === 'TTS first audio').source, 'browser');
  assert.equal(view.latency.find((item) => item.label === 'Total').value, '1.14 s');
});

test('clarification and handoff details appear only when provided', () => {
  const view = createTraceViewModel(snapshot({
    conversationStatus: 'handoff',
    latestTrace: { clarification: { question: 'Which claim?' }, handoff: {
      operator_queue: 'Claims', context_summary: 'Client requested an operator', reason: 'Complex case',
    } },
  }));
  assert.equal(view.clarification, 'Which claim?');
  assert.deepEqual(view.handoff, {
    queue: 'Claims', summary: 'Client requested an operator', reason: 'Complex case',
  });
  assert.equal(createTraceViewModel(snapshot({ conversationStatus: 'handoff' })).handoff, null);
});
