import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createTraceViewModel } from '../src/components/trace/traceViewModel.ts';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';

const nextTick = () => new Promise((resolve) => setImmediate(resolve));

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
