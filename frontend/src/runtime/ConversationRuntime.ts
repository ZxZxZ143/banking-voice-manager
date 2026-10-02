import type {
  AgentMessageResponse, ConversationMessage, ConversationStatus, RuntimeStatus, VoiceTranscript, ScenarioPackId,
} from '../types/agent';
import type { AgentClient } from '../services/agentClient';
import type { TtsService } from '../services/tts';
import { isScenarioPack, isSalesPack, scenarioPackNames } from '../types/agent.ts';
import { redactAuthentication } from './privacy.ts';
import { mayNeedPrecaution } from './securityCue.ts';

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
  safetyFirstAudioMs: number | null;
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
  safetyFirstAudioMs: null,
});

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

function replyLanguage(response: AgentMessageResponse, transcript: VoiceTranscript): string | undefined {
  const guard = typeof response.routing === 'object' && response.routing !== null
    && 'kind' in response.routing && response.routing.kind === 'security_guidance';
  for (const context of guard ? [response.routing, response.state] : [response.state, response.routing]) {
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
    if (!isScenarioPack(pack)) return;
    // Campaign selection belongs to the operator before a sales call starts.
    if (isSalesPack(pack) && isSalesPack(this.snapshot.activePack)
      && this.snapshot.sessionId && pack !== this.snapshot.activePack) return;
    this.update({ requestedPack: pack === this.snapshot.activePack ? null : pack });
    if (isSalesPack(pack) && pack !== this.snapshot.activePack
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
    await this.processTranscript(transcript, false, true);
  }

  private async processTranscript(transcript: VoiceTranscript, opening = false, voice = false): Promise<void> {
    const state = this.snapshot.latestState;
    const question = typeof state === 'object' && state !== null && 'pending_question' in state ? state.pending_question : null;
    const text = redactAuthentication(transcript.text.trim(), question).slice(0, 10_000);
    if ((!text && !opening) || this.disposed || this.snapshot.runtimeStatus !== 'listening' || !this.snapshot.sessionId) return;

    const generation = this.generation;
    const turnStarted = performance.now();
    this.update({ runtimeStatus: 'processing', error: null, sttLatencyMs: transcript.stt_ms ?? null, ttsFirstAudioMs: null, safetyFirstAudioMs: null });
    try {
      await this.runVoiceOperation('stopListening');
      if (!this.isCurrent(generation)) return;
      if (!opening) this.update({
        messages: [...this.snapshot.messages, {
          id: crypto.randomUUID(), role: 'user', text, timestamp: Date.now(),
        }],
      });
      const requestedPack = this.snapshot.requestedPack;
      // Keep one authoritative message request. Attach handlers immediately so a
      // provider error while early advice is spoken cannot become an unhandled rejection.
      const pendingResponse = (opening && this.agentClient.startScenario
        ? this.agentClient.startScenario({session_id: this.snapshot.sessionId,
          scenario_mode: requestedPack ?? this.snapshot.activePack})
        : this.agentClient.sendMessage({ session_id: this.snapshot.sessionId, text,
        ...(voice ? { channel: 'voice' as const } : {}),
        ...(requestedPack ? { scenario_mode: requestedPack } : {}),
      })).then(value => ({value}), error => ({error}));
      let spokenPrecaution = '';
      let precautionAudioMs: number | null = null;
      if (!opening && this.agentClient.securityPrecaution && mayNeedPrecaution(text)) {
        try {
          const language = typeof state === 'object' && state !== null && 'response_language' in state
            && state.response_language === 'kk' ? 'kk' : 'ru';
          const cue = await this.agentClient.securityPrecaution({text, response_language: language});
          if (!this.isCurrent(generation)) return;
          if (cue.response_text) {
            this.update({runtimeStatus: 'speaking'});
            const cueStarted = performance.now();
            const audio = await this.tts.speak(cue.response_text, cue.response_language);
            if (!this.isCurrent(generation)) return;
            spokenPrecaution = cue.response_text;
            precautionAudioMs = audio.firstAudioMs ?? null;
            this.update({safetyFirstAudioMs: audio.firstAudioMs === undefined ? null : cueStarted - turnStarted + audio.firstAudioMs});
          }
        } catch { /* Optional early advice failure leaves the authoritative turn intact. */ }
        if (!this.isCurrent(generation)) return;
        this.update({runtimeStatus: 'processing'});
      }
      const settled = await pendingResponse;
      if ('error' in settled) throw settled.error;
      const response = settled.value;
      if (!this.isCurrent(generation)) return;
      const trace = response.trace as Record<string, unknown> | undefined;
      const returnedPack = trace?.scenario_pack_id;
      const activePack = isScenarioPack(returnedPack)
        ? returnedPack : this.snapshot.activePack;
      this.update({
        activePack, requestedPack: null,
        packNotice: activePack !== this.snapshot.activePack
          ? `Переключено: ${scenarioPackNames[activePack]}`
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
      const remaining = spokenPrecaution && response.response_text.includes(spokenPrecaution)
        ? response.response_text.replace(spokenPrecaution, '').trim() : response.response_text;
      const ttsResult = remaining
        ? await this.tts.speak(remaining, replyLanguage(response, transcript)) : {};
      if (!this.isCurrent(generation)) return;
      this.update({ ttsFirstAudioMs: precautionAudioMs ?? ttsResult.firstAudioMs ?? null });
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
