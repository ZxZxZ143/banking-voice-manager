# Vonage outbound caller-ID investigation

The reported Dashboard rejection is **not caused by an omitted/string `from` in the
checked-in outbound caller**. The precise provider policy causing the rejection remains
unconfirmed. Request hardening does not establish that a subsequent live call will succeed.

Evidence collected using `/private/tmp/veyra-foundation-venv/bin/python`:

- Installed `vonage-voice` 1.5.1, `vonage-http-client` 1.5.2, Pydantic 2.13.5.
- The original code used `CreateCallRequest(from_=Phone(number=from_number),
  to=[ToPhone(number=to_number)])`, matching the official Python example.
- `Voice.create_call` calls `model_dump(by_alias=True, exclude_none=True)` and submits
  that dictionary as JSON through the SDK HTTP client. `from_` becomes `from`.
- Before the changes, an offline interception at `requests.Session.send` confirmed the
  final prepared HTTP body had the required phone endpoint objects. Tests cover both
  the trial CLI and another configured synthetic FROM, excluding a hardcoded trial value.
- With the current root `.env`, an offline interception confirmed FROM is the trial CLI,
  TO matches the reported destination, and both endpoints match runtime configuration.
  Credentials and actual destination values were not printed. No new call was placed.
- Authenticated read-only `GET /v1/calls/{uuid}` for
  `1ddf9e42-4c93-4532-a2df-cd08b8caf500` and
  `44e76852-4c7b-4b69-8493-b7b6943ea4dc` confirmed that Vonage retained the configured
  FROM and TO numbers for both existing calls. Both records returned `status=completed`.
  This conflicts with the reported Dashboard `FAILED / Unknown` view; it is not proof
  of a successful PSTN call or a completed voice conversation.

Before and after, the semantic JSON body of `POST https://api.nexmo.com/v1/calls` is
identical (object key order is immaterial). Destination and public origin are placeholders:

```json
{
  "from": {"type": "phone", "number": "123456789"},
  "to": [{"type": "phone", "number": "<configured signup phone number>"}],
  "answer_url": ["<PUBLIC_BASE_URL>/api/v1/telephony/vonage/answer"],
  "answer_method": "POST",
  "event_url": ["<PUBLIC_BASE_URL>/api/v1/telephony/vonage/events"],
  "event_method": "POST",
  "ringing_timer": 45,
  "length_timer": 600
}
```

The change explicitly sets `type="phone"` on the SDK endpoint objects and checks the
aliased JSON serialization before submission. Missing, string, or incorrect endpoints
raise a static configuration error before calling Vonage. The CLI enables operational
logging; the request diagnostic contains only configured flags, endpoint types, and
whether the configured FROM equals the documented trial CLI. It excludes numbers,
credentials, JWTs, key paths, and payloads. The SDK still owns HTTP serialization/auth.

Verification: 56 Vonage unit tests and 462 full backend tests passed. The prepared-body
regression passed on the original code too; the new guard is preventive hardening.
PhoneRuntime, STT, Agent, TTS, WebSocket audio and event architecture were not changed.

Remaining provider investigation: confirm that the application's account is still in
demo/trial mode and the destination is its original signup number. Vonage documents
the `123456789` exception only for demo/trial accounts until credit is added:
[official Voice getting-started guide](https://developer.vonage.com/en/voice/voice-api/getting-started).
If these conditions hold, provide the two UUIDs to Vonage support and ask them to reconcile
the stored caller ID and API status with the Dashboard's CLI rejection. Account eligibility
or carrier policy is an inference, not a verified exact cause. No purchase, account
change, support message, or additional live call was performed.
