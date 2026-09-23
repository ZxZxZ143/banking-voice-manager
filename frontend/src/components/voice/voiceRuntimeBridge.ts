import type { ConversationRuntime, VoiceInputController } from '../../runtime/ConversationRuntime';
import type { VoiceTranscript } from '../../types/agent';

export interface VoiceControlsHandle {
  startListening(sessionId: string): void;
  stopListening(): void;
}

export function createVoiceInputController(
  runtime: ConversationRuntime,
  getControls: () => VoiceControlsHandle | null,
): VoiceInputController {
  return {
    startListening: () => {
      const sessionId = runtime.getSnapshot().sessionId;
      const controls = getControls();
      if (!sessionId || !controls) throw new Error('Voice Input is not ready for this conversation.');
      controls.startListening(sessionId);
    },
    stopListening: () => { getControls()?.stopListening(); },
  };
}

export function finalVoiceTranscript(value: unknown): VoiceTranscript | null {
  if (typeof value !== 'object' || value === null || !('type' in value)
    || value.type !== 'utterance.final' || !('text' in value) || typeof value.text !== 'string') return null;
  const text = value.text.trim();
  if (!text) return null;
  const transcript: VoiceTranscript = { text };
  if ('language' in value && (value.language === 'ru' || value.language === 'kk' || value.language === 'mixed')) {
    transcript.language = value.language;
  }
  if ('stt_after_commit_ms' in value && typeof value.stt_after_commit_ms === 'number'
    && Number.isFinite(value.stt_after_commit_ms) && value.stt_after_commit_ms >= 0) {
    transcript.stt_ms = value.stt_after_commit_ms;
  }
  return transcript;
}
