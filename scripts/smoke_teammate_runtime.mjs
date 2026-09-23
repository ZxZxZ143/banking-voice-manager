/** Run the fetched teammate runtime against the live local API without checking out its branch. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { stripTypeScriptTypes } from 'node:module';

const ref = process.argv[2] ?? 'origin/feature/conversation-runtime';
const baseUrl = process.argv[3] ?? 'http://127.0.0.1:8000';
const revision = execFileSync('git', ['rev-parse', '--verify', ref], { encoding: 'utf8' }).trim();
async function importAtRef(path) {
  const source = execFileSync('git', ['show', `${revision}:${path}`], { encoding: 'utf8' });
  const code = stripTypeScriptTypes(source, { mode: 'transform' });
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}
const { ConversationRuntime } = await importAtRef('frontend/src/runtime/ConversationRuntime.ts');
const { HttpAgentClient } = await importAtRef('frontend/src/services/agentClient.ts');
const requests = [];
const httpClient = new HttpAgentClient(baseUrl, 60_000);
const runtime = new ConversationRuntime(
  { async sendMessage(request) {
    assert.deepEqual(Object.keys(request).sort(), ['session_id', 'text']);
    requests.push({ ...request });
    return httpClient.sendMessage(request);
  } },
  { async speak() { return {}; }, stop() {} }, // Explicit silent fixture, not actual TTS.
);
let listeningCount = 0;
runtime.attachVoiceInput({ startListening() { listeningCount += 1; }, stopListening() {} });
try {
  await runtime.startConversation();
  const session = runtime.getSnapshot().sessionId;
  await runtime.handleTranscript({ text: 'Хочу продлить страховку.', language: 'ru', stt_ms: 12 });
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening', runtime.getSnapshot().error);
  assert.equal(runtime.getSnapshot().latestState.turn_number, 1);
  assert.equal(runtime.getSnapshot().sttLatencyMs, 12); // Synthetic metadata remains runtime-local.
  await runtime.sendText('SQ-OGPO-104501');
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening', runtime.getSnapshot().error);
  assert.equal(runtime.getSnapshot().latestState.turn_number, 2);
  assert.equal(runtime.getSnapshot().latestState.slots.policy_number, 'SQ-OGPO-104501');
  assert.equal(runtime.getSnapshot().latestState.active_scenario, 'SC27');
  await runtime.sendText('Спасибо, до свидания!');
  assert.equal(runtime.getSnapshot().runtimeStatus, 'ended', runtime.getSnapshot().error);
  assert.equal(runtime.getSnapshot().conversationStatus, 'ended');
  assert.equal(runtime.getSnapshot().messages.length, 6);
  assert.ok(requests.every((request) => request.session_id === session));
  assert.equal(listeningCount, 3);
  console.log(JSON.stringify({
    result: 'PASS', revision, baseUrl, turns: requests.length,
    same_session: true, terminal_status: runtime.getSnapshot().conversationStatus,
    tts: 'silent fixture', stt: 'synthetic transcript metadata',
    client_timeout_ms: 60_000, routing: 'live backend',
  }, null, 2));
} finally {
  runtime.dispose();
}
