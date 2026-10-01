# Veyra channel and event foundation

Implemented in TypeScript alongside the existing frontend runtime. The current Saqta
Insurance demo and Agent Core are unchanged; finance intelligence is a separate workstream.

```text
Web channel (browser runtime)
  → ConversationRuntime → AgentClient → POST /api/message → Agent Core
          ↓                    ↑ response
    ConversationEvent → EventStore
```

Agent Core remains channel-agnostic: only `{session_id, text}` crosses `/api/message`.
Channel identity is exactly `web | phone` in `frontend/src/channels/channel.ts`. Each runtime has a fixed channel context (web by default).
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
  `routing.scenarios` or `routing.selections` only when trace scenarios are absent. This records Agent selections,
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

## Backend phone runtime

Phone execution lives entirely in `backend/app/telephony/`, reusing the existing backend
MessageService and server STT/TTS protocols. It does not instantiate a browser runtime or
route phone audio through React. The old TypeScript telephony interfaces remain transport
references only; the backend contracts are authoritative for phone integration.
See [PHONE_RUNTIME.md](PHONE_RUNTIME.md) for session identity/lifecycle, canonical PCM,
normalization, server events, test bench and the real-provider integration checklist.

Browser TTS and Phone TTS are different output adapters for the same Agent response.
Persistent storage and Analytics/Event API remain deferred; both event envelopes have the
same semantics for future ingestion. All new Veyra frontend UI must use shadcn/ui as its
primary design/component system. No UI redesign is included here.

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
