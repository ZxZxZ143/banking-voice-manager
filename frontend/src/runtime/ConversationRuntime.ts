import type {
  AgentMessageResponse, ConversationMessage, ConversationStatus, RuntimeStatus, VoiceTranscript, ScenarioPackId,
} from '../types/agent';
import type { AgentClient } from '../services/agentClient';
import type { TtsService } from '../services/tts';

export interface VoiceInputController {
  startListening(): Promise<void> | void;
  stopListening(): Promise<void> | void;
}

export interface ConversationSnapshot {
  activePack: ScenarioPackId;
  requestedPack: ScenarioPackId | null;
  packNotice: string | null;
  sessionId: string | null;
  runtimeStatus: RuntimeStatus;
  voiceInputEnabled: boolean;
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
  activePack: 'insurance_manager',
  requestedPack: null,
  packNotice: null,
  sessionId: null,
  runtimeStatus: 'idle',
  voiceInputEnabled: true,
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

function replyLanguage(response: AgentMessageResponse, transcript: VoiceTranscript): string | undefined {
  for (const context of [response.state, response.routing]) {
    if (typeof context === 'object' && context !== null && 'response_language' in context
      && (context.response_language === 'ru' || context.response_language === 'kk')) {
      return context.response_language;
    }
  }
  return transcript.language;
}

export class ConversationRuntime {
  private snapshot = initialSnapshot();
  private readonly listeners = new Set<() => void>();
  private generation = 0;
  private disposed = false;
  private voiceInput: VoiceInputController | null = null;
  private voiceOperation: Promise<void> = Promise.resolve();

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

  selectScenarioPack(pack: ScenarioPackId): void {
    if (this.disposed || !['idle', 'listening', 'error'].includes(this.snapshot.runtimeStatus)
      || this.snapshot.conversationStatus === 'handoff' || this.snapshot.conversationStatus === 'ended') return;
    if (pack !== 'insurance_manager' && pack !== 'product_promoter') return;
    this.update({ requestedPack: pack === this.snapshot.activePack ? null : pack });
    if (pack === 'product_promoter' && pack !== this.snapshot.activePack
      && this.snapshot.runtimeStatus === 'listening' && this.agentClient.startScenario) {
      void this.processTranscript({ text: '' }, true);
    }
  }

  async setVoiceInputEnabled(enabled: boolean): Promise<void> {
    if (this.disposed || this.snapshot.voiceInputEnabled === enabled) return;
    this.update({ voiceInputEnabled: enabled });
    const generation = this.generation;
    try {
      if (!enabled) await this.runVoiceOperation('stopListening');
      else if (this.snapshot.runtimeStatus === 'listening') await this.runVoiceOperation('startListening');
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  private runVoiceOperation(method: 'startListening' | 'stopListening'): Promise<void> {
    const controller = this.voiceInput;
    const generation = this.generation;
    if (!controller) return Promise.resolve();
    const operation = this.voiceOperation.then(() => {
      if (method === 'startListening' && (!this.isCurrent(generation)
        || !this.snapshot.voiceInputEnabled || this.snapshot.runtimeStatus !== 'listening'
        || this.snapshot.conversationStatus === 'handoff' || this.snapshot.conversationStatus === 'ended')) return;
      return controller[method]();
    });
    // A failed controller call is reported to its caller without blocking later stop/start calls.
    this.voiceOperation = operation.catch(() => {});
    return operation;
  }

  private update(patch: Partial<ConversationSnapshot>): void {
    if (this.disposed) return;
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  private fail(cause: unknown): void {
    // A playback/controller failure cannot undo a successful terminal API turn.
    const terminal = this.snapshot.conversationStatus;
    if (terminal === 'handoff' || terminal === 'ended') {
      this.update({ runtimeStatus: terminal, error: null });
      try { this.tts.stop(); } catch { /* The terminal reply remains visible. */ }
      void this.runVoiceOperation('stopListening').catch(() => {});
      return;
    }
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
      error: null,
    });
    try {
      if (this.agentClient.startScenario) await this.processTranscript({ text: '' }, true);
      else await this.runVoiceOperation('startListening');
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async endConversation(): Promise<void> {
    if (this.disposed) return;
    this.generation += 1;
    const generation = this.generation;
    // Stopping local capture/playback does not close the Agent Core session.
    const terminal = this.snapshot.conversationStatus;
    this.update({ runtimeStatus: terminal === 'handoff' ? 'handoff' : 'ended', error: null });
    try {
      this.tts.stop();
      await this.runVoiceOperation('stopListening');
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async resetConversation(): Promise<void> {
    if (this.disposed) return;
    this.generation += 1;
    const generation = this.generation;
    const selectedPack = this.snapshot.requestedPack ?? this.snapshot.activePack;
    this.update({ ...initialSnapshot(), voiceInputEnabled: this.snapshot.voiceInputEnabled,
      requestedPack: selectedPack === 'insurance_manager' ? null : selectedPack,
      sessionId: crypto.randomUUID() });
    try {
      this.tts.stop();
      await this.runVoiceOperation('stopListening');
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async sendText(text: string): Promise<void> {
    await this.processTranscript({ text });
  }

  async handleTranscript(transcript: VoiceTranscript): Promise<void> {
    // Reject even a late final event from capture cancelled by the text-only toggle.
    if (!this.snapshot.voiceInputEnabled) return;
    await this.processTranscript(transcript);
  }

  private async processTranscript(transcript: VoiceTranscript, opening = false): Promise<void> {
    const text = transcript.text.trim();
    if ((!text && !opening) || this.disposed || this.snapshot.runtimeStatus !== 'listening' || !this.snapshot.sessionId) return;

    const generation = this.generation;
    this.update({ runtimeStatus: 'processing', error: null, sttLatencyMs: transcript.stt_ms ?? null, ttsFirstAudioMs: null });
    try {
      await this.runVoiceOperation('stopListening');
      if (!this.isCurrent(generation)) return;
      if (!opening) this.update({
        messages: [...this.snapshot.messages, {
          id: crypto.randomUUID(), role: 'user', text, timestamp: Date.now(),
        }],
      });
      const requestedPack = this.snapshot.requestedPack;
      const response = opening && this.agentClient.startScenario
        ? await this.agentClient.startScenario({session_id: this.snapshot.sessionId,
          scenario_mode: requestedPack ?? this.snapshot.activePack})
        : await this.agentClient.sendMessage({ session_id: this.snapshot.sessionId, text,
        ...(requestedPack ? { scenario_mode: requestedPack } : {}),
      });
      if (!this.isCurrent(generation)) return;
      const trace = response.trace as Record<string, unknown> | undefined;
      const returnedPack = trace?.scenario_pack_id;
      const activePack = returnedPack === 'insurance_manager' || returnedPack === 'product_promoter'
        ? returnedPack : this.snapshot.activePack;
      this.update({
        activePack, requestedPack: null,
        packNotice: activePack !== this.snapshot.activePack
          ? `Переключено: ${activePack === 'product_promoter' ? 'Product Promoter' : 'Insurance Manager'}`
          : this.snapshot.packNotice,
        messages: [...this.snapshot.messages, {
          id: crypto.randomUUID(), role: 'assistant', text: response.response_text, timestamp: Date.now(),
        }],
        lastResponse: response,
        latestTrace: response.trace ?? null,
        latestState: response.state ?? null,
        conversationStatus: response.conversation_status,
        runtimeStatus: 'speaking',
      });
      const ttsResult = await this.tts.speak(response.response_text, replyLanguage(response, transcript));
      if (!this.isCurrent(generation)) return;
      this.update({ ttsFirstAudioMs: ttsResult.firstAudioMs ?? null });
      if (response.conversation_status === 'handoff' || response.conversation_status === 'ended') {
        this.update({ runtimeStatus: response.conversation_status });
        return;
      }
      this.update({ runtimeStatus: 'listening' });
      await this.runVoiceOperation('startListening');
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
      void this.runVoiceOperation('stopListening').catch(() => {});
    } catch {
      // Teardown must not crash an unmounting UI.
    }
    this.voiceInput = null;
  }
}
