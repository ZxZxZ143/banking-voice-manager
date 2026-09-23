from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/api/v1/voice")
async def voice(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "error": {
                "code": "not_implemented",
                "message": (
                    "Voice transport is not implemented. No audio was recorded or generated."
                ),
            }
        }
    )
    await websocket.close(code=1013, reason="Voice transport not implemented")
