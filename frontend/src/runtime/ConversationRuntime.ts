import type {
  AgentMessageResponse, ConversationMessage, ConversationStatus, RuntimeStatus, VoiceTranscript,
} from '../types/agent';
import type { AgentClient } from '../services/agentClient';
import type { TtsService } from '../services/tts';
import type { ChannelContext } from '../channels/channel';
import { createConversationEvent } from '../events/ConversationEvent.ts';
import type { ConversationEvent, ConversationEventType } from '../events/ConversationEvent';
import { InMemoryEventStore } from '../events/EventStore.ts';
import type { EventStore } from '../events/EventStore';

export interface ConversationRuntimeOptions {
  channel?: ChannelContext;
  /** A phone adapter can bind its incoming call correlation ID before starting. */
  sessionId?: string;
  eventStore?: EventStore;
  onEventError?: (cause: unknown) => void;
}

export interface VoiceInputController {
  startListening(): Promise<void> | void;
  stopListening(): Promise<void> | void;
}

export interface ConversationSnapshot {
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
  private sessionOpen = false;
  readonly channel: ChannelContext;
  readonly eventStore: EventStore;

  constructor(
    private readonly agentClient: AgentClient,
    private readonly tts: TtsService,
    private readonly options: ConversationRuntimeOptions = {},
  ) {
    this.channel = structuredClone(options.channel ?? { channel: 'web' });
    if (this.channel.channel !== 'web' && this.channel.channel !== 'phone') {
      throw new Error('Unsupported conversation channel.');
    }
    this.eventStore = options.eventStore ?? new InMemoryEventStore();
    if (options.sessionId) this.snapshot = { ...this.snapshot, sessionId: options.sessionId };
  }

  private record(eventType: ConversationEventType, fields: Partial<ConversationEvent> = {}): void {
    if (!this.snapshot.sessionId) return;
    const report = (cause: unknown) => {
      try {
        if (this.options.onEventError) this.options.onEventError(cause);
        else console.warn('Conversation event recording failed.');
      } catch { /* Diagnostics must not break the conversation either. */ }
    };
    try {
      const event = createConversationEvent({
        ...fields,
        session_id: this.snapshot.sessionId,
        event_type: eventType,
        channel: this.channel.channel,
        metadata: { ...fields.metadata, channel_metadata: this.channel.metadata },
      });
      // Do not await persistence or let it add latency/failure to a user turn.
      void Promise.resolve(this.eventStore.append(structuredClone(event))).catch(report);
    } catch (cause) { report(cause); }
  }

  private closeSession(reason: 'local_stop' | 'reset' | 'dispose' | 'agent_status'): void {
    if (!this.sessionOpen) return;
    this.sessionOpen = false;
    this.record('conversation.ended', {
      conversation_status: this.snapshot.conversationStatus ?? undefined,
      metadata: { reason },
    });
  }

  private recordResponse(response: AgentMessageResponse): void {
    const record = (value: unknown): Record<string, unknown> =>
      typeof value === 'object' && value !== null && !Array.isArray(value)
        ? value as Record<string, unknown> : {};
    const trace = record(response.trace);
    const routing = record(response.routing);
    const fields = {
      conversation_status: response.conversation_status,
      risk: response.risk, routing: response.routing, state: response.state, trace: response.trace,
      language: typeof trace.language === 'string' ? trace.language : undefined,
      action: trace.actions, latency: trace.latency_ms,
    };
    this.record('agent.response', { ...fields, text: response.response_text });
    // Record supplied selections in their original order; never select a route here.
    const scenarios = Array.isArray(trace.scenarios)
      ? trace.scenarios : routing.scenarios ?? routing.selections;
    if (Array.isArray(scenarios)) {
      for (const scenario of scenarios) {
        const selection = record(scenario);
        this.record('scenario.selected', {
          ...fields, scenario,
          confidence: typeof selection.confidence === 'number' ? selection.confidence : undefined,
        });
      }
    }
    if (trace.clarification === true
      || (typeof routing.clarification_question === 'string' && routing.clarification_question.trim())) {
      this.record('clarification.requested', {
        ...fields,
        clarification: typeof routing.clarification_question === 'string' ? routing.clarification_question : true,
      });
    }
    if (trace.handoff === true || response.conversation_status === 'handoff') {
      this.record('handoff.requested', { ...fields, handoff: true });
    }
    if (response.conversation_status === 'ended' || response.conversation_status === 'handoff') {
      this.closeSession('agent_status');
    }
  }

  getSnapshot = (): ConversationSnapshot => this.snapshot;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  attachVoiceInput(controller: VoiceInputController | null): void {
    this.voiceInput = controller;
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
    if (!controller) return Promise.resolve();
    const operation = this.voiceOperation.then(() => {
      if (method === 'startListening' && !this.snapshot.voiceInputEnabled) return;
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
    if (!this.sessionOpen) {
      this.sessionOpen = true;
      this.record('session.started');
    }
    try {
      await this.runVoiceOperation('startListening');
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async endConversation(): Promise<void> {
    if (this.disposed) return;
    this.closeSession('local_stop');
    this.generation += 1;
    const generation = this.generation;
    // Stopping local capture/playback does not close the Agent Core session.
    this.update({ runtimeStatus: 'ended', error: null });
    try {
      this.tts.stop();
      await this.runVoiceOperation('stopListening');
    } catch (cause) {
      if (this.isCurrent(generation)) this.fail(cause);
    }
  }

  async resetConversation(): Promise<void> {
    if (this.disposed) return;
    this.closeSession('reset');
    this.generation += 1;
    const generation = this.generation;
    this.update({ ...initialSnapshot(), voiceInputEnabled: this.snapshot.voiceInputEnabled, sessionId: crypto.randomUUID() });
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

  private async processTranscript(transcript: VoiceTranscript): Promise<void> {
    const text = transcript.text.trim();
    if (!text || this.disposed || this.snapshot.runtimeStatus !== 'listening' || !this.snapshot.sessionId) return;

    const generation = this.generation;
    this.record('transcript.final', {
      text, language: transcript.language,
      latency: transcript.stt_ms === undefined ? undefined : { stt: transcript.stt_ms },
    });
    this.update({ runtimeStatus: 'processing', error: null, sttLatencyMs: transcript.stt_ms ?? null, ttsFirstAudioMs: null });
    try {
      await this.runVoiceOperation('stopListening');
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
      this.recordResponse(response);
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
    this.closeSession('dispose');
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
