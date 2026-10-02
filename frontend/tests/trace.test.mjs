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

test('scenario pack metadata is additive and legacy traces remain readable', () => {
  const view = createTraceViewModel(snapshot({ latestTrace: {
    scenario_pack_id: 'insurance_manager', interaction_mode: 'consultative',
    context_lifecycle: 'completed', scenario_mode: 'legacy',
  } }));
  assert.equal(view.scenarioMode, 'insurance_manager');
  assert.equal(view.interactionMode, 'consultative');
  assert.equal(view.contextLifecycle, 'completed');
  const legacy = createTraceViewModel(snapshot({ latestTrace: { scenario_mode: 'insurance_manager' } }));
  assert.equal(legacy.scenarioMode, 'insurance_manager');
  assert.equal(legacy.interactionMode, null);
  assert.equal(legacy.contextLifecycle, null);
});

test('boolean clarification and handoff from the real API retain visible details', () => {
  const clarification = createTraceViewModel(snapshot({
    latestTrace: { clarification: true, scenario_mode: 'insurance_manager' },
    lastResponse: { response_text: 'Новый полис или проблема с существующим?' },
  }));
  assert.equal(clarification.clarification, 'Новый полис или проблема с существующим?');
  assert.equal(clarification.scenarioMode, 'insurance_manager');
  const terminal = createTraceViewModel(snapshot({
    conversationStatus: 'handoff', latestTrace: { handoff: true, reason: 'Operator requested' },
  }));
  assert.equal(terminal.handoff.reason, 'Operator requested');
});

test('manager handoff exposes field names and real checks supplied by the server', () => {
  const summary = {
    reason: 'operation_requires_human', scenario: 'SC04',
    collected_fields: ['phone', 'policy_number', 'new_driver_iin'], known_client: true,
    completed_read_only_checks: ['find_client', 'get_policy', 'get_bm_class'],
    next_required_action: 'update_policy',
  };
  const view = createTraceViewModel(snapshot({
    conversationStatus: 'handoff', latestTrace: { handoff: true, manager_summary: summary },
  }));
  assert.equal(view.handoff.reason, summary.reason);
  assert.deepEqual(JSON.parse(view.handoff.summary), summary);
  assert.equal(view.packSwitch, null);
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
