import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRiskView, createFraudCaseView } from '../src/components/security/securityViewModel.ts';
import { redactAuthentication } from '../src/runtime/privacy.ts';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';
import { isSalesPack, isScenarioPack } from '../src/types/agent.ts';

test('risk panel allowlists taxonomy, handles unavailable assessment and ignores arbitrary secret fields', () => {
  assert.equal(createRiskView(null), null);
  assert.equal(createRiskView({level: 'confirmed_fraud', analysis_status: 'analyzed'}), null);
  const view = createRiskView({level: 'high', analysis_status: 'analyzed', risk_relevant: true,
    signals: ['otp_requested_by_third_party', 'otp_requested_by_third_party', 'secret_value'],
    recommended_action: 'freeze_account', secret: 'private'});
  assert.deepEqual(view.signals, ['otp_requested_by_third_party']);
  assert.equal(view.action, null);
  assert.equal(JSON.stringify(view).includes('private'), false);
  assert.equal(createRiskView({level: 'none', analysis_status: 'unavailable'}).status, 'unavailable');
});

test('Fraud case is separate from SalesLead and malformed data is not inferred', () => {
  assert.equal(isScenarioPack('fraud_security'), true);
  assert.equal(isSalesPack('fraud_security'), false);
  assert.equal(createFraudCaseView({scenario_mode: 'card_promoter', fraud_case: {}}), null);
  assert.equal(createFraudCaseView({scenario_mode: 'fraud_security', fraud_case: {}}), null);
  const view = createFraudCaseView({scenario_mode: 'fraud_security', fraud_case: {
    case_type: 'credential_exposure', case_status: 'needs_review', handoff: true,
    facts: ['otp_disclosed'], otp: '654321'}});
  assert.equal(view.handoff, true);
  assert.deepEqual(view.facts, ['otp_disclosed']);
  assert.equal(JSON.stringify(view).includes('654321'), false);
});

test('mask volunteered secrets without breaking ordinary identification', () => {
  for (const text of ['SMS код: 654321', 'PIN 7248', 'CVV=741', 'мой пароль SpringSecret42', 'Карта 4111 2222 3333 4444']) {
    const safe = redactAuthentication(text);
    assert.match(safe, /скрыт/);
    assert.equal(redactAuthentication(safe), safe);
  }
  assert.equal(redactAuthentication('Телефон 77010000001 ИИН 000101300000'), 'Телефон 77010000001 ИИН 000101300000');
  assert.equal(redactAuthentication('сообщил пароль SpringSecret42').includes('SpringSecret42'), false);
  assert.equal(redactAuthentication('SMS код один два три четыре пять шесть').includes('один два три'), false);
  assert.equal(redactAuthentication('Да, 654321', 'exposure').includes('654321'), false);
});

test('voice security response stays in campaign, sends one masked turn, speaks actual risk reply language', async () => {
  const calls = [], spoken = [];
  const runtime = new ConversationRuntime({
    startScenario: async r => ({response_text: 'Предлагаю карту', conversation_status: 'active', trace: {scenario_pack_id: r.scenario_mode}}),
    sendMessage: async r => { calls.push(r); return {response_text: 'Кодты айтпаңыз.', conversation_status: 'active',
      routing: {kind: 'security_guidance', response_language: 'kk'}, state: {response_language: 'ru', sales_lead: {product_category: 'card'}},
      trace: {scenario_pack_id: 'card_promoter'}, risk: {level: 'high', analysis_status: 'analyzed'}}; },
  }, {speak: async (text, lang) => {spoken.push([text, lang]); return {};}, stop() {}});
  runtime.selectScenarioPack('card_promoter');
  await runtime.startConversation();
  await runtime.handleTranscript({text: 'SMS код: 654321'});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].channel, 'voice');
  assert.equal(calls[0].text.includes('654321'), false);
  assert.equal(runtime.getSnapshot().activePack, 'card_promoter');
  assert.equal(runtime.getSnapshot().messages.filter(m => m.role === 'user').length, 1);
  assert.equal(spoken.at(-1)[1], 'kk');
  assert.equal(JSON.stringify(runtime.getSnapshot()).includes('654321'), false);
  runtime.selectScenarioPack('fraud_security');
  assert.equal(runtime.getSnapshot().requestedPack, 'fraud_security');
  runtime.dispose();
});

test('source precaution is heard while the model is pending, with one user/API turn and no repeated warning', async () => {
  let resolveAgent;
  const requests = [], spoken = [];
  const cue = 'Не сообщайте код.';
  const runtime = new ConversationRuntime({sendMessage: async r => {
    requests.push(r); return new Promise(resolve => {resolveAgent = resolve;});
  }, securityPrecaution: async () => ({response_text: cue, response_language: 'ru'})},
  {speak: async text => {spoken.push(text); return {firstAudioMs: 4};}, stop() {}});
  await runtime.setVoiceInputEnabled(false);
  await runtime.startConversation();
  const pending = runtime.sendText('Просят SMS код');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(spoken, [cue]);
  assert.equal(requests.length, 1);
  assert.equal(runtime.getSnapshot().messages.length, 1);
  resolveAgent({response_text: `${cue} Завершите звонок.`, conversation_status: 'active', trace: {scenario_pack_id: 'insurance_manager'}});
  await pending;
  assert.deepEqual(spoken, [cue, 'Завершите звонок.']);
  assert.equal(runtime.getSnapshot().messages.filter(m => m.role === 'user').length, 1);
  assert.equal(runtime.getSnapshot().messages.filter(m => m.role === 'assistant').length, 1);
  assert.equal(runtime.getSnapshot().messages.at(-1).text, `${cue} Завершите звонок.`);
  assert.equal(runtime.getSnapshot().ttsFirstAudioMs, 4);
  runtime.dispose();
});

test('failed early advice still preserves the authoritative response and terminal behavior', async () => {
  const runtime = new ConversationRuntime({sendMessage: async () => ({response_text: 'Конечно, передаю диалог оператору.', conversation_status: 'handoff'}),
    securityPrecaution: async () => {throw new Error('Precaution unavailable');}},
    {speak: async () => ({}), stop() {}});
  await runtime.setVoiceInputEnabled(false);
  await runtime.startConversation();
  await runtime.sendText('Просят SMS код, дайте оператора');
  assert.equal(runtime.getSnapshot().conversationStatus, 'handoff');
  assert.equal(runtime.getSnapshot().runtimeStatus, 'handoff');
  assert.equal(runtime.getSnapshot().messages.length, 2);
  runtime.dispose();
});
