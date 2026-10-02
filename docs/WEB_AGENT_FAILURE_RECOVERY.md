# Browser Agent turn failure recovery

The user-observed HTTP 502 message matches `router_invalid_output`, raised as
`RouterOutputError` when SDK output/decision validation or decision policy rejects
a result. It is not evidence of a transport timeout (504), closed session (409),
or malformed browser AgentResponse. Existing failed-router API tests prove that
failure does not commit dialog history/state/trace and that a same-session retry
can succeed. The exact rejected field/SDK exception for the historical live turn
was not logged and cannot be reconstructed from its safe HTTP message alone.
No Router prompt/model/validation/business logic was changed in this fix.

`backend/app/api/routes/message.py` now logs `web agent_turn_failed` before returning
the existing error response, with structured `error_code`, `failure_layer`, wrapper
and deepest cause class, safe application message, allowlisted `validation_reason`,
HTTP status, elapsed time and numeric provider status when present. Layers distinguish
provider, timeout, SDK/output validation, policy validation and configuration.
Raw exception strings/tracebacks can include prompt, slot and credential content,
so root diagnostics are deliberately withheld; the safe message and actual cause
class are logged instead. No transcript, session ID, request body, JWT/key or
private response is logged. Expected invalid-decision example (class/reason depend
on the actual next failure):

```text
web agent_turn_failed {'error_code': 'router_invalid_output', 'failure_layer': 'router_output_validation', 'exception_type': 'RouterOutputError', 'root_exception_type': 'ModelBehaviorError', 'safe_message': 'The routing provider returned an invalid decision; please retry or contact an operator.', 'root_message': 'details withheld; see failure_layer and validation_reason', 'validation_reason': 'invalid_structure', 'http_status': 502, 'elapsed_ms': ...}
```

Before: ConversationRuntime stopped capture before Agent submission, then every
Agent rejection left runtimeStatus=error. Incoming transcripts/text required
runtimeStatus=listening, so microphone auto-resume and ordinary retry stopped.
After: browser recoverable HTTP/network/timeout failures leave the error visible,
return to listening, restart capture only if voice input remains enabled and the
session remains open, and accept a new user utterance in the same session. No
automatic Agent resend or fabricated assistant response/TTS occurs. Successful
retry still waits for TTS completion before resuming capture.

Nonrecoverable HTTP responses (including 409 session/channel conflict and auth/input
errors) and malformed successful replies retain error state. TTS/voice-controller
failures retain their previous error behavior. Handoff/ended, reset, local stop and
dispose prevent stale callbacks/queued microphone restarts. The phone-channel
failure policy and all backend phone/Vonage/Twilio code remain unchanged.

Offline checks include actual HttpAgentClient 502 → success with deferred TTS,
same-session retry, visible error, text-only toggle, reset/stop/dispose stale errors,
terminal statuses, nonrecoverable 409, phone-policy preservation, safe root-cause
logging and policy-vs-Router distinction. These do not prove that the upstream
invalid-decision issue has disappeared; repeat a real browser turn with the updated
backend to capture the new diagnostics if it recurs.

Verified checks: 80 frontend tests (nine new recovery checks), 544 full backend
tests (four new safe-log checks), TypeScript noEmit, Vite production build, backend
Ruff lint/format and Git diff check. Focused message/Router tests also passed.
Commands: `node --import tsx --test tests/*.test.mjs`, `tsc --noEmit`, `vite build`
from frontend; `python -m pytest backend/tests -q`,
`ruff check backend/app backend/tests`, `ruff format --check backend/app backend/tests`
from the repository root, using the existing local tool environments.
