# Veyra channel and event foundation

Implemented in TypeScript alongside the existing frontend runtime. The current Saqta
Insurance demo and Agent Core are unchanged; finance intelligence is a separate workstream.

```text
Channel (web today / phone adapter later)
  → ConversationRuntime → AgentClient → POST /api/message → Agent Core
          ↓                    ↑ response
    ConversationEvent → EventStore
```

Agent Core remains channel-agnostic: only `{session_id, text}` crosses `/api/message`.
Channel identity is `web | phone | mobile` in `frontend/src/channels/channel.ts`; mobile is
reserved, with no integration. Each runtime has a fixed channel context (web by default).
Channel metadata is copied into `event.metadata.channel_metadata` and must use synthetic,
non-secret correlation data. It must not contain credentials or real customer data.

## Event contract

`frontend/src/events/ConversationEvent.ts` defines:

| Fields | Types / meaning |
|---|---|
| `id`, `session_id`, `timestamp` | Required strings; UUID event ID, runtime correlation ID, UTC ISO 8601 time |
| `event_type`, `channel` | Required `ConversationEventType` and `Channel` |
| `language`, `text` | Optional strings; supplied language and final transcript/reply text |
| `scenario`, `action` | Optional opaque Agent values; one supplied selection and supplied trace actions |
| `confidence` | Optional number copied from the selection; no frontend scoring |
| `conversation_status` | Optional existing `ConversationStatus` |
| `clarification`, `handoff` | Optional boolean/string and boolean, respectively |
| `risk`, `routing`, `state`, `trace` | Optional values reusing `AgentMessageResponse` indexed types (`unknown` until Core contracts are published) |
| `latency` | Optional supplied trace latency object, or `{stt: number}` for an input transcript |
| `metadata` | Optional `Record<string, unknown>` extension object |

`createConversationEvent(input, identity?)` supplies UUID/time by default; tests can supply
an explicit ID/time. Optional payloads may be missing, null, partial, or additive.
Only response text and conversation status remain required by the existing Agent client.
AgentMessageResponse now also declares optional `session_id` and opaque optional `risk`.

The seven event types are:

- `session.started`: once when the runtime starts a session; retries keep the existing start.
- `transcript.final`: nonblank accepted text/final voice input while listening. Partial STT
  remains in the voice UI and never reaches an Agent turn or this event.
- `agent.response`: after a current-generation successful response, before TTS. Keeps text
  and Agent routing/state/trace/risk unchanged; HTTP errors never produce a fabricated reply.
- `scenario.selected`: one per supplied trace scenario, in source order; falls back to
  `routing.selections` only when trace scenarios are absent. This records Agent selections,
  including uncertain/system selections, and does not assert policy acceptance/execution.
- `clarification.requested`: explicit `trace.clarification === true` or nonblank
  `routing.clarification_question`; awaiting-user status alone does not imply clarification.
- `handoff.requested`: explicit `trace.handoff === true` or handoff conversation status;
  records a request, not a completed operator transfer.
- `conversation.ended`: records runtime-session closure once, with `metadata.reason` of
  `local_stop`, `reset`, `dispose`, or `agent_status`. The last Agent status is preserved.
  `agent_status` applies to both terminal ended and handoff responses, even if TTS then fails.
  Local closure does not close or rewrite the backend session.

Reset closes the old stream before allocating a new ID. Late responses after reset/stop
remain excluded by the runtime's existing generation guard. No second state machine or
business decision layer is introduced.

## EventStore

`frontend/src/events/EventStore.ts` exposes:

```ts
append(event: ConversationEvent): void | Promise<void>
getBySession(sessionId: string): ConversationEvent[] | Promise<ConversationEvent[]>
list(filter?: EventFilter): ConversationEvent[] | Promise<ConversationEvent[]>
// EventFilter: session_id?, channel?, event_type?, limit?
```

`InMemoryEventStore(maxEvents = 5000)` keeps append order, including equal or out-of-order
timestamps; oldest events are evicted at capacity. Filters preserve that order, and limit
returns the first matching events (`0` returns none). Append and reads deep-copy payloads.
Reads are synchronous in this implementation. Async replacements must preserve append
invocation order and define their read consistency; the runtime does not wait for writes.

Each runtime has its own default store, available as `runtime.eventStore`. A shared store
can be injected in constructor options. Records survive runtime reset/dispose while that
store remains referenced; reload/process exit loses them. There is no API or shared server
event feed yet. Persistent storage is intentionally deferred. EventStore will later feed
Journey, Anomaly Detection, and Analytics API; those consumers are not implemented.

Writes are best effort, with synchronous throws and rejected promises isolated from
conversation flow. Pending async writes do not delay an Agent call or TTS. The runtime
also copies data before dispatch so a sink cannot mutate Agent state. Default failure
diagnostics are a static warning without payloads; optional `onEventError` receives the
cause, and its failures are isolated too. A failed event is not retried in this foundation.

## Future phone adapter

`frontend/src/channels/TelephonyProvider.ts` defines provider-neutral interfaces:

- `PhoneCall`: `callId`, `sessionId`, literal `channel: 'phone'`, optional metadata.
- `AudioChunk`: bytes, encoding, sample rate, channel count; no provider framing assumption.
- `TelephonyProvider`: incoming-call subscription with unsubscribe, incoming audio async
  stream, outgoing audio async stream, and hangup.
- `PhoneTranscriptSource`: subscription to final, normalized `VoiceTranscript` values.

A future provider adapter owns audio framing, STT/TTS, stream cancellation and call
lifecycle. It creates one runtime per call, using `options.sessionId = call.sessionId`
(a valid `/api/message` correlation ID) and a phone channel context. It binds capture through
the existing `VoiceInputController`, final STT through `handleTranscript`, and outgoing
speech through an injected `TtsService`. Hangup uses local `endConversation()`/`dispose()`
and the provider's `hangup()`; the provider owns that glue. These dependency boundaries
allow a future adapter without changing Runtime or Agent Core. This contract is a skeleton,
not a live phone integration; Twilio/Telnyx/SIP choice and SDKs are intentionally deferred.

```ts
const store = new InMemoryEventStore();
const runtime = new ConversationRuntime(agentClient, phoneTts, {
  sessionId: call.sessionId,
  channel: { channel: 'phone', metadata: { call_id: call.callId } },
  eventStore: store,
});
// Bind VoiceInputController and final transcript subscription, then start the runtime.
const events = await store.getBySession(call.sessionId);
```

## Verification

From `frontend`: `npm run test:events`, existing `test:runtime`, `test:tts`, `test:trace`,
`test:integration`, `test:voice-bridge`, plus `npm run typecheck` and `npm run build`.
`frontend/tests/events.test.mjs` covers shape, copies, order/capacity/filtering, web/phone
identity, final-only STT, existing MockAgentClient, partial HTTP finance replies, explicit
clarification/handoff, stale responses, closure, logging failures and sink mutation.
Live microphone/provider/model functionality is not verified by these deterministic tests.

Verified on 2026-10-01 with bundled Node 24 and a temporary Python 3.12 environment using
`backend/requirements.lock`: all 36 frontend tests (24 existing + 12 new), all 307 backend
tests, TypeScript checking, production Vite build, and `git diff --check` passed.
