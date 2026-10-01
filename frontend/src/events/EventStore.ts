import type { ConversationEvent, ConversationEventType } from './ConversationEvent';
import type { Channel } from '../channels/channel';

type StoreResult<T> = T | Promise<T>;

export interface EventFilter {
  session_id?: string;
  channel?: Channel;
  event_type?: ConversationEventType;
  limit?: number;
}

export interface EventStore {
  /** Implementations must preserve append invocation order, including asynchronous writes. */
  append(event: ConversationEvent): StoreResult<void>;
  getBySession(sessionId: string): StoreResult<ConversationEvent[]>;
  list(filter?: EventFilter): StoreResult<ConversationEvent[]>;
}

/** Bounded, per-runtime memory; oldest events are evicted at capacity. No persistence. */
export class InMemoryEventStore implements EventStore {
  private readonly events: ConversationEvent[] = [];

  constructor(private readonly maxEvents = 5_000) {
    if (!Number.isInteger(maxEvents) || maxEvents < 1) throw new Error('maxEvents must be a positive integer.');
  }

  append(event: ConversationEvent): void {
    this.events.push(structuredClone(event));
    if (this.events.length > this.maxEvents) this.events.shift();
  }

  getBySession(sessionId: string): ConversationEvent[] {
    return this.list({ session_id: sessionId });
  }

  list(filter: EventFilter = {}): ConversationEvent[] {
    if (filter.limit !== undefined && (!Number.isInteger(filter.limit) || filter.limit < 0)) {
      throw new Error('limit must be a nonnegative integer.');
    }
    const matches = this.events.filter(event =>
      (filter.session_id === undefined || event.session_id === filter.session_id)
      && (filter.channel === undefined || event.channel === filter.channel)
      && (filter.event_type === undefined || event.event_type === filter.event_type));
    return structuredClone(filter.limit === undefined ? matches : matches.slice(0, filter.limit));
  }
}
