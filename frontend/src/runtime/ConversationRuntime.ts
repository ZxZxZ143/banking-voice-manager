import type {
  AgentMessageResponse, ConversationMessage, ConversationStatus, RuntimeStatus, VoiceTranscript,
} from '../types/agent';
import type { AgentClient } from '../services/agentClient';
import type { TtsService } from '../services/tts';

export interface VoiceInputController {
  startListening(): Promise<void> | void;
  stopListening(): Promise<void> | void;
}

export interface ConversationSnapshot {
  sessionId: string | null;
  runtimeStatus: RuntimeStatus;
  conversationStatus: ConversationStatus | null;
  messages: ConversationMessage[];
  lastResponse: AgentMessageResponse | null;
  error: string | null;
  latestTrace: unknown;
  latestState: unknown;
  sttLatencyMs: number | null;
  ttsFirstAudioMs: number | null;
}

const initialSnapshot = (): ConversationSnapshot => ({
  sessionId: null,
  runtimeStatus: 'idle',
  conversationStatus: null,
  messages: [],
  lastResponse: null,
  error: null,
  latestTrace: null,
  latestState: null,
  sttLatencyMs: null,
  ttsFirstAudioMs: null,
});

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export class ConversationRuntime {
  private snapshot = initialSnapshot();
  private readonly listeners = new Set<() => void>();
  private generation = 0;
  private disposed = false;
  private voiceInput: VoiceInputController | null = null;

  constructor(
    private readonly agentClient: AgentClient,
    private readonly tts: TtsService,
  ) {}

  getSnapshot = (): ConversationSnapshot => this.snapshot;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  attachVoiceInput(controller: VoiceInputController | null): void {
    this.voiceInput = controller;
  }

  private update(patch: Partial<ConversationSnapshot>): void {
    if (this.disposed) return;
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  private fail(cause: unknown): void {
    this.update({ runtimeStatus: 'error', error: errorMessage(cause) });
  }

  private isCurrent(generation: number): boolean {
    return !this.disposed && generation === this.generation;
  }

  async startConversation(): Promise<void> {
    if (this.disposed || !['idle', 'error'].includes(this.snapshot.runtimeStatus)) return;
    if (this.snapshot.conversationStatus === 'ended' || this.snapshot.conversationStatus === 'handoff') return;
    const generation = this.generation;
    this.update({
      sessionId: this.snapshot.sessionId ?? crypto.randomUUID(),
      runtimeStatus: 'listening',
      conversationStatus: this.snapshot.conversationStatus ?? 'active',
      error: null,
    });
    try {
      await this.voiceInput?.startListening();
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async endConversation(): Promise<void> {
    if (this.disposed) return;
    this.generation += 1;
    const generation = this.generation;
    this.update({ runtimeStatus: 'ended', conversationStatus: 'ended', error: null });
    try {
      this.tts.stop();
      await this.voiceInput?.stopListening();
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async resetConversation(): Promise<void> {
    if (this.disposed) return;
    this.generation += 1;
    const generation = this.generation;
    this.update({ ...initialSnapshot(), sessionId: crypto.randomUUID() });
    try {
      this.tts.stop();
      await this.voiceInput?.stopListening();
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async sendText(text: string): Promise<void> {
    await this.handleTranscript({ text });
  }

  async handleTranscript(transcript: VoiceTranscript): Promise<void> {
    const text = transcript.text.trim();
    if (!text || this.disposed || this.snapshot.runtimeStatus !== 'listening' || !this.snapshot.sessionId) return;

    const generation = this.generation;
    this.update({ runtimeStatus: 'processing', error: null, sttLatencyMs: transcript.stt_ms ?? null, ttsFirstAudioMs: null });
    try {
      await this.voiceInput?.stopListening();
      if (!this.isCurrent(generation)) return;
      this.update({
        messages: [...this.snapshot.messages, {
          id: crypto.randomUUID(), role: 'user', text, timestamp: Date.now(),
        }],
      });
      const response = await this.agentClient.sendMessage({ session_id: this.snapshot.sessionId, text });
      if (!this.isCurrent(generation)) return;
      this.update({
        messages: [...this.snapshot.messages, {
          id: crypto.randomUUID(), role: 'assistant', text: response.response_text, timestamp: Date.now(),
        }],
        lastResponse: response,
        latestTrace: response.trace ?? null,
        latestState: response.state ?? null,
        conversationStatus: response.conversation_status,
        runtimeStatus: 'speaking',
      });
      const ttsResult = await this.tts.speak(response.response_text, transcript.language);
      if (!this.isCurrent(generation)) return;
      this.update({ ttsFirstAudioMs: ttsResult.firstAudioMs ?? null });
      if (response.conversation_status === 'handoff' || response.conversation_status === 'ended') {
        this.update({ runtimeStatus: response.conversation_status });
        return;
      }
      this.update({ runtimeStatus: 'listening' });
      await this.voiceInput?.startListening();
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.generation += 1;
    this.disposed = true;
    this.listeners.clear();
    try {
      this.tts.stop();
      void Promise.resolve(this.voiceInput?.stopListening()).catch(() => {});
    } catch {
      // Teardown must not crash an unmounting UI.
    }
    this.voiceInput = null;
  }
}
