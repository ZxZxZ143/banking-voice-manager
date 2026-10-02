import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';
import { createSalesLeadView } from '../src/components/conversation/salesLeadViewModel.ts';
import { createTraceViewModel } from '../src/components/trace/traceViewModel.ts';

const tts = { speak: async () => ({}), stop() {} };

test('explicit selector switches on next turn, keeps UUID/history, then resumes default current pack', async () => {
  const requests = [];
  let active = 'insurance_manager';
  const runtime = new ConversationRuntime({ sendMessage: async request => {
    requests.push(request);
    active = request.scenario_mode ?? active;
    return { response_text: 'Условия продукта', conversation_status: 'active',
      trace: { scenario_pack_id: active }, state: { response_language: 'ru' } };
  } }, tts);
  await runtime.setVoiceInputEnabled(false);
  await runtime.startConversation();
  const id = runtime.getSnapshot().sessionId;
  await runtime.sendText('Страховка');
  runtime.selectScenarioPack('product_promoter');
  assert.equal(runtime.getSnapshot().activePack, 'insurance_manager');
  await runtime.sendText('Депозит');
  assert.equal(runtime.getSnapshot().activePack, 'product_promoter');
  assert.equal(runtime.getSnapshot().packNotice, 'Переключено: Product Promoter');
  await runtime.sendText('Снятие нужно');
  runtime.selectScenarioPack('insurance_manager');
  await runtime.sendText('Продолжим страховку');
  assert.deepEqual(requests.map(r => r.scenario_mode), [undefined, 'product_promoter', undefined, 'insurance_manager']);
  assert.ok(requests.every(r => r.session_id === id));
  assert.equal(runtime.getSnapshot().messages.length, 8);
  runtime.dispose();
});

test('failed switching keeps active pack and pending selection for retry', async () => {
  const runtime = new ConversationRuntime({ sendMessage: async () => { throw new Error('Provider unavailable'); } }, tts);
  await runtime.setVoiceInputEnabled(false);
  await runtime.startConversation();
  runtime.selectScenarioPack('product_promoter');
  await runtime.sendText('Депозит');
  assert.equal(runtime.getSnapshot().activePack, 'insurance_manager');
  assert.equal(runtime.getSnapshot().requestedPack, 'product_promoter');
  assert.equal(runtime.getSnapshot().runtimeStatus, 'error');
  runtime.dispose();
});

test('selector cannot race processing and late response cannot switch reset session', async () => {
  let resolve;
  const runtime = new ConversationRuntime({ sendMessage: () => new Promise(r => { resolve = r; }) }, tts);
  await runtime.setVoiceInputEnabled(false);
  await runtime.startConversation();
  const turn = runtime.sendText('Страховка');
  await new Promise(r => setImmediate(r));
  runtime.selectScenarioPack('product_promoter');
  assert.equal(runtime.getSnapshot().requestedPack, null);
  await runtime.resetConversation();
  resolve({ response_text: 'Late', conversation_status: 'active', trace: { scenario_pack_id: 'product_promoter' } });
  await turn;
  assert.equal(runtime.getSnapshot().activePack, 'insurance_manager');
  assert.equal(runtime.getSnapshot().messages.length, 0);
  runtime.dispose();
});

test('natural confirmation uses backend pack ID and voice final uses the generic request', async () => {
  const requests = [];
  const runtime = new ConversationRuntime({ sendMessage: async request => {
    requests.push(request);
    return { response_text: 'Ответ', conversation_status: 'active', trace: {
      scenario_pack_id: requests.length === 1 ? 'insurance_manager' : 'product_promoter' },
      state: { response_language: 'kk' } };
  } }, tts);
  await runtime.startConversation();
  await runtime.handleTranscript({ text: 'Депозит керек' });
  await runtime.handleTranscript({ text: 'Иә' });
  assert.equal(runtime.getSnapshot().activePack, 'product_promoter');
  assert.ok(requests.every(r => !Object.hasOwn(r, 'scenario_mode')));
  assert.equal(requests[0].session_id, requests[1].session_id);
  runtime.dispose();
});

test('SalesLeadResult view renders supplied values and ignores malformed state', () => {
  assert.equal(createSalesLeadView({ scenario_mode: 'insurance_manager', sales_lead: {} }), null);
  assert.equal(createSalesLeadView(null), null);
  const view = createSalesLeadView({ scenario_mode: 'product_promoter', sales_lead: {
    outcome: 'interested', product_category: 'deposit', selected_product_id: 'DEP-FLEX',
    presented_products: ['DEP-FLEX', null], compared_products: [], objections: ['yield'],
    interest_level: 'high', next_action: 'application_interest',
    customer_preferences: { amount: 50000, currency: 'KZT', liquidity: true, other: null },
  } });
  assert.equal(view.selected, 'DEP-FLEX');
  assert.deepEqual(view.presented, ['DEP-FLEX']);
  assert.equal(view.preferences.length, 3);
});

test('supervisor shows actual product fields and cross-pack lifecycle without deriving a recommendation', () => {
  const view = createTraceViewModel({ latestTrace: {
    scenario_pack_id: 'product_promoter', interaction_mode: 'proactive', context_lifecycle: 'resumed',
    product_category: 'card', presented_products: ['CARD-DAILY'], selected_product_id: null,
    lead_status: 'consulting', next_action: 'continue_consultation',
    pack_switch: { from_pack: 'insurance_manager', to_pack: 'product_promoter', status: 'switched' },
  }, latestState: null, lastResponse: null, conversationStatus: 'active' });
  assert.equal(view.selectedProduct, null);
  assert.deepEqual(view.presentedProducts, ['CARD-DAILY']);
  assert.equal(view.contextLifecycle, 'resumed');
  assert.match(view.packSwitch, /insurance_manager → product_promoter/);
});

test('proactive pack speaks a backend opener before listening and never fabricates user input', async () => {
  const events = [];
  const runtime = new ConversationRuntime({
    startScenario: async request => { events.push(['open', request]); return {
      response_text: 'Здравствуйте! Я консультант Merei Demo Bank.', conversation_status: 'active',
      trace: { scenario_pack_id: 'product_promoter', event_type: 'scenario.opened' },
    }; },
    sendMessage: async request => { events.push(['message', request]); return {
      response_text: 'Депозит от 50 тысяч тенге.', conversation_status: 'active',
      trace: { scenario_pack_id: 'product_promoter' },
    }; },
  }, { speak: async text => { events.push(['tts', text]); return {}; }, stop() {} });
  runtime.attachVoiceInput({ startListening: () => { events.push(['listen']); }, stopListening() {} });
  runtime.selectScenarioPack('product_promoter');
  await runtime.startConversation();
  assert.deepEqual(events.map(e => e[0]), ['open', 'tts', 'listen']);
  assert.equal(runtime.getSnapshot().messages.length, 1);
  assert.equal(runtime.getSnapshot().messages[0].role, 'assistant');
  const id = runtime.getSnapshot().sessionId;
  await runtime.handleTranscript({text: 'Хочу депозит'});
  assert.equal(events.find(e => e[0] === 'message')[1].session_id, id);
  assert.equal(runtime.getSnapshot().messages.length, 3);
  runtime.dispose();
});

test('switching into proactive pack while listening starts the backend conversation immediately', async () => {
  let opened = 0;
  const runtime = new ConversationRuntime({
    startScenario: async request => { opened++; return { response_text: 'Приветствие', conversation_status: 'active',
      trace: { scenario_pack_id: request.scenario_mode } }; },
    sendMessage: async () => { throw new Error('No customer request expected'); },
  }, tts);
  await runtime.setVoiceInputEnabled(false);
  await runtime.startConversation();
  const id = runtime.getSnapshot().sessionId;
  runtime.selectScenarioPack('product_promoter');
  await new Promise(r => setImmediate(r));
  assert.equal(opened, 2);
  assert.equal(runtime.getSnapshot().activePack, 'product_promoter');
  assert.equal(runtime.getSnapshot().sessionId, id);
  assert.equal(runtime.getSnapshot().messages[0].role, 'assistant');
  runtime.dispose();
});

test('insurance starts with an assistant-only opener and TTS finishes before capture', async () => {
  const events = [];
  const runtime = new ConversationRuntime({
    startScenario: async request => { events.push(['open', request]); return {
      response_text: 'Здравствуйте! Saqta Insurance. Чем могу помочь?',
      conversation_status: 'active', trace: { scenario_pack_id: 'insurance_manager' },
    }; },
    sendMessage: async () => { throw new Error('No fabricated customer turn'); },
  }, { speak: async () => { events.push(['tts']); return {}; }, stop() {} });
  runtime.attachVoiceInput({ startListening() { events.push(['listen']); }, stopListening() {} });
  await runtime.startConversation();
  assert.deepEqual(events.map(e => e[0]), ['open', 'tts', 'listen']);
  assert.equal(events[0][1].scenario_mode, 'insurance_manager');
  assert.deepEqual(runtime.getSnapshot().messages.map(m => m.role), ['assistant']);
  runtime.dispose();
});
