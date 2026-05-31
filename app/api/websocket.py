from fastapi import APIRouter, Query, WebSocket

from app.core.exceptions import AuthException
from app.core.security import decode_token
from app.websocket.detection_handler import handle_detection_socket

router = APIRouter()


def _user_id_from_token(token: str) -> int:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise AuthException("Invalid token")
    return int(payload["sub"])


@router.websocket("/ws/users/me/detections")
async def ws_detections(ws: WebSocket, token: str = Query(...)):
    try:
        user_id = _user_id_from_token(token)
    except AuthException:
        await ws.close(code=4401)
        return
    await handle_detection_socket(ws, user_id)
