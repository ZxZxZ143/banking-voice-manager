# Agent Core — 3 Hour Implementation Plan

## Goal

Build the smallest reliable Agent Core that can:
- accept text from STT/frontend;
- preserve one conversation across multiple turns;
- route RU/KZ/mixed requests to one or more scenarios;
- clarify instead of guessing;
- keep scenario context;
- return a short grounded response;
- expose trace + latency;
- be evaluated on `dev_utterances.json`.

The agent must **not** finish after one response. One `/api/message` call = one conversation turn.

---

## 1. `/api/message` + session lifecycle

- [ ] Implement `POST /api/message`
- [ ] Input:

```json
{
  "session_id": "abc123",
  "text": "Хочу продлить полис и добавить сына"
}
```

- [ ] Reuse the same `session_id` across turns
- [ ] Return:

```json
{
  "session_id": "abc123",
  "response_text": "...",
  "routing": {},
  "state": {},
  "trace": {},
  "conversation_status": "active"
}
```

Supported statuses:

```text
active
awaiting_user
awaiting_confirmation
handoff
ended
```

---

## 2. `DialogueState`

- [ ] Implement an in-memory state store
- [ ] Keep only what is needed:

```text
session_id
turn_number
language
client_id
active_scenario
scenario_stack
pending_scenarios
slots
unclear_count
awaiting_confirmation
conversation_status
history
```

- [ ] Preserve state between `/api/message` calls
- [ ] Do not add a database

---

## 3. Router Agent

- [ ] Load compact scenario catalog from `scenarios.json`
- [ ] Use:
  - `scenario_id`
  - `name`
  - `description`
  - `not_this_if`
  - `priority`
  - selected examples
- [ ] One LLM call should perform:
  - language detection
  - semantic decomposition
  - scenario routing
  - alternatives
  - slot extraction
  - continuation detection
- [ ] Support:
  - single intent
  - multi-intent
  - RU
  - KZ
  - mixed
  - `SYS_UNCLEAR`
  - `SYS_OUT_OF_SCOPE`
  - `SYS_GOODBYE`

Suggested structured output:

```json
{
  "language": "ru",
  "segments": [
    {
      "text": "Хочу продлить полис",
      "scenario_id": "SC27",
      "confidence": 0.94,
      "reason": "Existing policy needs renewal"
    },
    {
      "text": "добавить сына",
      "scenario_id": "SC04",
      "confidence": 0.91,
      "reason": "Client wants to add a driver"
    }
  ],
  "scenarios": ["SC27", "SC04"],
  "alternatives": [],
  "slots": {},
  "is_continuation": false
}
```

Do not add RAG.

---

## 4. Confidence policy + clarification

- [ ] Add configurable thresholds
- [ ] Start with:

```text
>= 0.75 → accept
0.45–0.75 → clarify
< 0.45 repeatedly → handoff
```

- [ ] If ambiguous, do not guess
- [ ] Ask one short clarification using top alternatives
- [ ] Increment `unclear_count`
- [ ] Prevent infinite clarification loops
- [ ] Explicit operator request → `handoff`

Example:

```text
SC17 vs SC19
→ "Вы хотите узнать статус заявления или оспорить принятое решение?"
```

---

## 5. Scenario continuity + stack

- [ ] If the user is answering the current scenario, treat it as continuation
- [ ] Do not reroute slot-only answers as new intents
- [ ] If user changes topic:
  - push current scenario into `scenario_stack`
  - activate new scenario
- [ ] For multi-intent:
  - first scenario → `active_scenario`
  - remaining → `pending_scenarios`
- [ ] Urgent scenario goes first
- [ ] Otherwise keep spoken order
- [ ] After a side scenario finishes, allow return to previous scenario

---

## 6. Basic response

- [ ] Return a short response for every turn
- [ ] Use current language (`ru` / `kk`)
- [ ] Use scenario opening/closing templates where useful
- [ ] Use `knowledge_base.json` for factual answers
- [ ] Use `mock_backend.json` only when client/policy/claim data is needed
- [ ] Do not invent missing facts
- [ ] Ask only one missing slot at a time

For the 3-hour MVP, implement only the minimum read-only helpers needed for good demo behavior:

```text
find_client
get_policy
get_claim
kb_lookup
```

Do not try to implement every action now.

---

## 7. Trace + latency

- [ ] Create one trace record per user turn
- [ ] Store:

```text
session_id
turn_number
transcript
language
scenarios
confidence
alternatives
reason
slots
clarification
active_scenario
pending_scenarios
handoff
conversation_status
```

- [ ] Measure:

```text
router_ms
policy_ms
response_ms
agent_total_ms
```

- [ ] Keep trace in memory or JSONL
- [ ] Do not expose chain-of-thought

---

## 8. Evaluation

- [ ] Add batch runner:

```text
dev_utterances.json
→ Router Agent
→ predictions.json
```

- [ ] Run:

```bash
python evaluate.py predictions.json dev_utterances.json
```

- [ ] Record:
  - primary accuracy
  - full match
  - multi-intent recall
  - errors
- [ ] Fix general routing rules, not exact test phrases
- [ ] Re-run after every prompt/router change

Priority boundary pairs:

```text
SC01 / SC02
SC11 / SC12 / SC13
SC17 / SC18 / SC19
SC21 / SC22 / SC23
SC25 / SC26 / SC30
SC35 / SC19
SC39 / SC26
SC40 / SC22
```

---

# If time remains

Only after the checklist above works:

- [ ] add explicit confirmation flow for irreversible actions
- [ ] add 2–3 more backend actions needed for the demo
- [ ] improve prompt based on evaluation errors

Do not start analytics, Supabase, RAG, embeddings, or a multi-agent architecture.

---

# Suggested order for the 3 hours

## First 60 min
- `/api/message`
- `DialogueState`
- scenario loader
- structured Router Agent

## Next 60 min
- confidence policy
- clarification
- multi-intent
- continuation / scenario stack
- basic response

## Final 60 min
- trace + latency
- `dev_utterances.json` batch runner
- run `evaluate.py`
- fix the largest routing errors
- integration smoke test with frontend/voice contract

---

# Definition of Done

The Agent Core is ready for integration when this loop works:

```text
POST /api/message
        ↓
load DialogueState
        ↓
route / continue / clarify
        ↓
update state
        ↓
generate response
        ↓
save trace
        ↓
return response
        ↓
WAIT FOR NEXT TURN
```

The conversation ends only when:

```text
conversation_status = ended
```

or:

```text
conversation_status = handoff
```

A completed scenario does not automatically end the conversation.
