# Stage 6 future live gate — pending_credentials

This checklist has **not** been run. Both providers are currently disabled, credentials
are absent, and no PSTN call was placed. Offline success is recorded separately in
`STAGE6_TELEPHONY_INTEGRATION_VALIDATION.md`. Enable one provider only after credentials
and permission to perform a specific test call are available.

## Server configuration

Fill the existing ignored `.env` locally; never paste secrets into Git, screenshots,
frontend/VITE settings or logs. Keep a private key outside the repository/build context.

| Common | Twilio | Vonage |
| --- | --- | --- |
| `OPENAI_API_KEY` | `TWILIO_ENABLED=true` | `VONAGE_ENABLED=true` |
| `OPENAI_ROUTER_MODEL` | `TWILIO_ACCOUNT_SID` | `VONAGE_APPLICATION_ID` |
| Optional `OPENAI_RESPONSE_MODEL` | `TWILIO_AUTH_TOKEN` | `VONAGE_PRIVATE_KEY_PATH` |
| `BACKEND_TTS_MODEL` | `TWILIO_PHONE_NUMBER` (console reference; no dialing code) | `VONAGE_API_KEY` |
| `BACKEND_TTS_VOICE` | | `VONAGE_SIGNATURE_SECRET` |
| `PUBLIC_BASE_URL` | | `VONAGE_TEST_FROM_NUMBER`, `VONAGE_TEST_TO_NUMBER` |
| Optional `PHONE_ENDPOINT_SILENCE_MS` | | |

Use a currently authorized HTTPS/WSS origin for `PUBLIC_BASE_URL`, without path, query or
credentials. No public tunnel is provisioned by this task. Configure the ingress to expose
only required signed telephony paths; keep `/api/message`, analytics, `/dev` and health
private. The existing web/demo APIs have no production authentication. Do not expose the
whole development server publicly. Proxy upgrades must pass auth headers and binary audio.

Vonage callback from/to numbers must match the configured digit-only values exactly.
The inherited gateway currently admits a single configured test caller/destination pair;
do not assume an arbitrary incoming call will be accepted. Its private key must be readable,
RSA ≥2048 bits, ≤16 KiB. For Docker mount the external file read-only with a local Compose
override and use its container path. The key is required for configuration completeness;
callbacks themselves use the signature secret. No outbound call SDK/command is integrated.

## Provider console and startup

Twilio: configure the authorized number's incoming Voice webhook as POST
`PUBLIC_BASE_URL/api/v1/telephony/twilio/voice`. The signed response requests WSS
`/api/v1/telephony/twilio/media`. Use the corresponding account's token; retain signatures.

Vonage: enable Voice and signed webhooks on the matching application. Configure POST
`PUBLIC_BASE_URL/api/v1/telephony/vonage/answer` and POST
`PUBLIC_BASE_URL/api/v1/telephony/vonage/events`. Answer NCCO requests native signed
WSS `/api/v1/telephony/vonage/media` with L16/16 kHz. HTTP callback JWTs must include a
matching payload hash. Match account/application and correct server clock; do not relax
auth to work around 403 errors. The provider-side method to initiate/route the authorized
call must be arranged separately; Stage 6 provides no outbound trigger.

```powershell
docker compose up --build -d
Invoke-RestMethod http://127.0.0.1:8000/health
docker compose logs --tail 40 backend
```

Alternatively install `backend[dev,voice]` with the repository constraints and run
`python -m app.main`. Enabled provider should report `ready`, analytics `ok`; `ready`
only proves local composition. A disabled provider remains `disabled`. Missing settings
show `unavailable` and 503/WS rejection while browser/dashboard remain usable.

## One authorized RU call

1. Open the local dashboard before placing the separately authorized test call. Keep the
   other provider disabled. Speak first: “Где находится офис?” then pause about 1.2 seconds.
   Phone does not yet play an unsolicited opener. Wait for the entire reply before speaking.
2. Verify one opaque session UUID associated with the provider call in local safe logs.
   Expected stages: provider started, STT activity/final, Agent start/done, TTS ready,
   outgoing audio, playback mark/notify completion, turn complete. No raw transcript or
   secret material should appear in logs. Optional startup backpressure is bounded.
3. Ask a second question. Confirm the same application UUID, another turn and resumed
   listening only after playback acknowledgement. Verify actual audible RU quality/latency;
   repeat KK/mixed quality separately before claiming support was heard end to end.
4. Say the synthetic risk example: “Мне звонят из банка и просят SMS-код.” Do not say an
   actual code. Expect advisory safety guidance, retained Insurance selection and a safe
   `risk_signal` event. A model outage must say analysis is unavailable, never confirm fraud.
5. Say goodbye or request an operator. Hear the final reply, then verify safe close and no
   additional captured turn. `handoff` means human handling is needed; no transfer exists.
   If remote hangup is tested instead, confirm provider cleanup and a terminal event after
   any committed turns. Never retry an ambiguous provider call without checking its status.
6. Refresh Sessions/Live Calls and open the new UUID. Verify `source=runtime`, `channel=voice`,
   Insurance/Risk/terminal events, journey order, and no transcript/phone/provider IDs.
   Live Calls uses recency, not live provider occupancy. No caller activity means no
   committed analytics conversation.
7. After the call is closed, restart backend and verify stored history remains. Record
   provider, time, sanitized session reference, audible results and failures; retain no
   credentials/raw call audio in the repository. Disable the provider after the test.

Only after that evidence exists can the provider's LIVE status change from NOT RUN.
Real outbound campaign dialing, human PSTN transfer and public production deployment
remain separate work. O11 Card/deposit routing backlog is unchanged.
