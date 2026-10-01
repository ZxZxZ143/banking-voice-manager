import type { VoiceTranscript } from '../types/agent';

/** TypeScript transport reference. Live phone execution belongs to backend/app/telephony. */
export interface AudioChunk {
  data: Uint8Array;
  encoding: string;
  sampleRateHz: number;
  channels: number;
}

export interface PhoneCall {
  callId: string;
  /** Correlation ID used unchanged for the runtime and AgentClient. */
  sessionId: string;
  channel: 'phone';
  metadata?: Record<string, unknown>;
}

/** Skeleton only: no provider SDK, call handling, or real operator transfer. */
export interface TelephonyProvider {
  onIncomingCall(handler: (call: PhoneCall) => void): () => void;
  incomingAudio(callId: string): AsyncIterable<AudioChunk>;
  sendAudio(callId: string, audio: AsyncIterable<AudioChunk>): Promise<void>;
  hangup(callId: string): Promise<void>;
}

/** Reference only; phone transcripts and STT/TTS are processed on the backend. */
export interface PhoneTranscriptSource {
  onFinalTranscript(callId: string, handler: (transcript: VoiceTranscript) => void): () => void;
}
