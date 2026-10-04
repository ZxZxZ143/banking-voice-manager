import type {
  ConversationRuntime,
  VoiceInputController,
} from "../../runtime/ConversationRuntime";
import type { VoiceTranscript } from "../../types/agent";

export interface VoiceControlsHandle {
  prepareListening?(sessionId: string): Promise<void> | void;
  playbackReference?(blob: Blob): Promise<void> | void;
  armNearEnd?(seconds: number): void;
  pauseListening?(): void;
  startListening(sessionId: string): Promise<void> | void;
  stopListening(): void;
}

export function createVoiceInputController(
  runtime: ConversationRuntime,
  getControls: () => VoiceControlsHandle | null,
): VoiceInputController {
  return {
    prepareListening: () => {
      const sessionId = runtime.getSnapshot().sessionId;
      if (sessionId) return getControls()?.prepareListening?.(sessionId);
    },
    playbackReference: (blob) => getControls()?.playbackReference?.(blob),
    armNearEnd: (seconds) => getControls()?.armNearEnd?.(seconds),
    pauseListening: () => {
      const controls = getControls();
      if (controls?.pauseListening) controls.pauseListening();
      else controls?.stopListening();
    },
    startListening: () => {
      const sessionId = runtime.getSnapshot().sessionId;
      const controls = getControls();
      if (!sessionId || !controls)
        throw new Error("Voice Input is not ready for this conversation.");
      return controls.startListening(sessionId);
    },
    stopListening: () => {
      getControls()?.stopListening();
    },
  };
}

export function finalVoiceTranscript(value: unknown): VoiceTranscript | null {
  if (
    typeof value !== "object" ||
    value === null ||
    !("type" in value) ||
    value.type !== "utterance.final" ||
    !("text" in value) ||
    typeof value.text !== "string"
  )
    return null;
  const text = value.text.trim();
  if (!text) return null;
  const transcript: VoiceTranscript = { text };
  if (
    "recognition_id" in value &&
    typeof value.recognition_id === "string" &&
    /^[0-9a-f-]{36}$/.test(value.recognition_id)
  )
    transcript.recognition_id = value.recognition_id;
  if (
    "language" in value &&
    (value.language === "ru" ||
      value.language === "kk" ||
      value.language === "mixed")
  ) {
    transcript.language = value.language;
  }
  if (
    "stt_after_commit_ms" in value &&
    typeof value.stt_after_commit_ms === "number" &&
    Number.isFinite(value.stt_after_commit_ms) &&
    value.stt_after_commit_ms >= 0
  ) {
    transcript.stt_ms = value.stt_after_commit_ms;
  }
  return transcript;
}
