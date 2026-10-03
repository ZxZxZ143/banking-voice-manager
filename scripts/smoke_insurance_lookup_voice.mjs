/** Synthetic STT finals through the actual runtime + live backend. No acoustic claims. */
import assert from 'node:assert/strict';
import { ConversationRuntime } from '../frontend/src/runtime/ConversationRuntime.ts';
import { HttpAgentClient } from '../frontend/src/services/agentClient.ts';
import { finalVoiceTranscript } from '../frontend/src/components/voice/voiceRuntimeBridge.ts';

const http = new HttpAgentClient(process.argv[2] ?? 'http://127.0.0.1:8000', 60_000);
let requests = 0;
let starts = 0;
const runtime = new ConversationRuntime({
  startScenario: request => http.startScenario(request),
  sendMessage: request => { requests += 1; return http.sendMessage(request); },
}, { speak: async () => ({}), stop() {} }); // Explicit silent TTS fixture.
runtime.attachVoiceInput({ startListening() { starts += 1; }, stopListening() {} });
try {
  await runtime.startConversation();
  const session = runtime.getSnapshot().sessionId;
  const turns = [
    ['Хочу продлить мой полис', 'policy_number'],
    ['У меня нет номера полиса', 'phone'],
    ['87770001234', 'iin'],
    ['000000000000', null],
  ];
  for (const [text, expected] of turns) {
    assert.equal(finalVoiceTranscript({ type: 'transcript.partial', text }), null);
    const before = requests;
    const final = finalVoiceTranscript({ type: 'utterance.final', text, language: 'ru' });
    await runtime.handleTranscript(final);
    const snapshot = runtime.getSnapshot();
    assert.equal(snapshot.error, null);
    assert.equal(requests, before + 1, 'one final creates one HTTP turn');
    assert.equal(snapshot.latestState.turn_number, requests + 1); // Includes opener.
    assert.equal(snapshot.sessionId, session);
    assert.equal(snapshot.latestTrace.expected_slot, expected);
    assert.equal(snapshot.latestTrace.repair_attempts, 0);
  }
  const result = runtime.getSnapshot();
  assert.equal(result.runtimeStatus, 'handoff');
  assert.equal(result.latestTrace.manager_summary.reason, 'lookup_exhausted');
  assert.deepEqual(result.latestTrace.manager_summary.unavailable_fields, ['policy_number']);
  const started = starts;
  await runtime.handleTranscript({ text: 'Late final' });
  assert.equal(requests, turns.length);
  assert.equal(starts, started);
  console.log(JSON.stringify({ result: 'PASS', turns: requests, one_final_one_turn: true,
    same_session: true, terminal: 'handoff', stt: 'synthetic finals', tts: 'silent fixture' }));
} finally {
  runtime.dispose();
}
