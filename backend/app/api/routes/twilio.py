"""Public Twilio endpoints; signatures are required even in local development."""

from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import FormData

from app.telephony.providers.twilio_messages import AccountSid, CallSid
from app.telephony.twilio_gateway import MEDIA_PATH, VOICE_PATH

router = APIRouter()
call_adapter = TypeAdapter(CallSid)
account_adapter = TypeAdapter(AccountSid)


@router.post(VOICE_PATH)
async def voice(request: Request):
    gateway = request.app.state.twilio_gateway
    if gateway is None:
        raise HTTPException(503, "Twilio phone runtime is not configured")
    if request.url.query:
        raise HTTPException(400, "Query parameters are not supported")
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Expected Twilio form data")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, "Webhook body too large")
    try:
        params = FormData(
            parse_qsl(
                body.decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=100,
            )
        )
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid form data") from None
    if not gateway.valid_signature(
        VOICE_PATH, request.headers.get("x-twilio-signature", ""), params
    ):
        raise HTTPException(403, "Invalid Twilio signature")
    try:
        call_id = call_adapter.validate_python(params.get("CallSid"))
        account = account_adapter.validate_python(params.get("AccountSid"))
        if account != gateway.account_sid:
            raise ValueError("Account mismatch")
        xml = gateway.admit(call_id)
    except (ValueError, ValidationError):
        raise HTTPException(400, "Invalid or unavailable call") from None
    return Response(xml, media_type="application/xml")


@router.websocket(MEDIA_PATH)
async def media(socket: WebSocket):
    gateway = socket.app.state.twilio_gateway
    if (
        gateway is None
        or socket.url.query
        or not gateway.valid_signature(
            MEDIA_PATH, socket.headers.get("x-twilio-signature", ""), {}, websocket=True
        )
    ):
        await socket.close(code=1008)
        return
    await socket.accept()
    await gateway.serve(socket)
