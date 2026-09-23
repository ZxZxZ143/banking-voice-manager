import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createVoiceInputController, finalVoiceTranscript } from '../src/components/voice/voiceRuntimeBridge.ts';
import { ConversationRuntime } from '../src/runtime/ConversationRuntime.ts';
import { MockAgentClient } from '../src/services/agentClient.ts';

test('only a nonempty final event becomes a runtime transcript', () => {
  assert.equal(finalVoiceTranscript({ type: 'transcript.partial', text: 'часть' }), null);
  assert.equal(finalVoiceTranscript({ type: 'empty' }), null);
  assert.equal(finalVoiceTranscript({ type: 'error', message: 'offline' }), null);
  assert.equal(finalVoiceTranscript({ type: 'utterance.final', text: '  ' }), null);
  assert.deepEqual(finalVoiceTranscript({
    type: 'utterance.final', text: '  Привет  ', language: 'ru', stt_after_commit_ms: 589,
  }), { text: 'Привет', language: 'ru', stt_ms: 589 });
  assert.deepEqual(finalVoiceTranscript({
    type: 'utterance.final', text: 'Сәлем', language: null, stt_after_commit_ms: -1,
  }), { text: 'Сәлем' });
  assert.deepEqual(finalVoiceTranscript({
    type: 'utterance.final', text: 'Аралас', language: 'mixed',
  }), { text: 'Аралас', language: 'mixed' });
});

test('voice controller bridge reuses runtime session through mock agent and TTS', async () => {
  const voiceSessions = [];
  const spoken = [];
  let stops = 0;
  const controls = {
    startListening: (sessionId) => { voiceSessions.push(sessionId); },
    stopListening: () => { stops += 1; },
  };
  const runtime = new ConversationRuntime(new MockAgentClient(), {
    speak: async (text, language) => { spoken.push({ text, language }); return { firstAudioMs: 12 }; },
    stop() {},
  });
  runtime.attachVoiceInput(createVoiceInputController(runtime, () => controls));

  await runtime.startConversation();
  await runtime.handleTranscript(finalVoiceTranscript({
    type: 'utterance.final', text: 'Первый вопрос', language: 'kk', stt_after_commit_ms: 589,
  }));
  assert.equal(runtime.getSnapshot().runtimeStatus, 'listening');
  assert.equal(runtime.getSnapshot().sttLatencyMs, 589);
  assert.equal(runtime.getSnapshot().ttsFirstAudioMs, 12);
  assert.equal(spoken[0].language, 'kk');

  await runtime.handleTranscript(finalVoiceTranscript({
    type: 'utterance.final', text: 'Второй вопрос', language: null, stt_after_commit_ms: 420,
  }));
  assert.equal(runtime.getSnapshot().messages.length, 4);
  assert.equal(voiceSessions.length, 3);
  assert.equal(new Set(voiceSessions).size, 1);
  assert.equal(voiceSessions[0], runtime.getSnapshot().sessionId);
  assert.equal(spoken[1].language, undefined);

  await runtime.resetConversation();
  const stoppedAtReset = stops;
  await runtime.handleTranscript({ text: 'Поздний ответ' });
  assert.equal(runtime.getSnapshot().messages.length, 0);
  assert.equal(stops, stoppedAtReset);
  runtime.dispose();
});
