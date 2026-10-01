"""Signed Vonage answer/events and WebSocket; deliberately no public dialing endpoint."""

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket

from app.telephony.providers.vonage_messages import Answer, CallEvent
from app.telephony.vonage_calls import ANSWER_PATH, EVENTS_PATH, MEDIA_PATH

router = APIRouter()


async def signed_body(request: Request):
    gateway = request.app.state.vonage_gateway
    if gateway is None:
        raise HTTPException(503, "Vonage phone runtime is not configured")
    if (
        request.url.query
        or request.headers.get("content-type", "").split(";")[0] != "application/json"
    ):
        raise HTTPException(400, "Expected JSON without query parameters")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, "Webhook body too large")
    if not gateway.authenticate(request.headers.get("authorization", ""), bytes(body)):
        raise HTTPException(403, "Invalid Vonage authentication")
    return gateway, bytes(body)


@router.post(ANSWER_PATH)
async def answer(request: Request):
    gateway, body = await signed_body(request)
    try:
        return gateway.answer(Answer.model_validate_json(body))
    except ValueError:
        raise HTTPException(400, "Invalid or unavailable trial call") from None


@router.post(EVENTS_PATH)
async def events(request: Request):
    gateway, body = await signed_body(request)
    try:
        event = CallEvent.model_validate_json(body)
    except ValueError:
        raise HTTPException(400, "Invalid call event") from None
    await gateway.event(event)
    return Response(status_code=204)


@router.websocket(MEDIA_PATH)
async def media(socket: WebSocket):
    gateway = socket.app.state.vonage_gateway
    if (
        gateway is None
        or socket.url.query
        or not gateway.authenticate(socket.headers.get("authorization", ""))
    ):
        await socket.close(code=1008)
        return
    await socket.accept()
    await gateway.serve(socket)
