from fastapi import APIRouter, Query, WebSocket

from app.core.exceptions import AuthException
from app.core.security import USER_ACCESS_SOURCES, decode_access_token
from app.websocket.detection_handler import handle_detection_socket

router = APIRouter()


@router.websocket("/ws/users/me/detections")
async def ws_detections(ws: WebSocket, token: str = Query(...)):
    try:
        claims = decode_access_token(token, USER_ACCESS_SOURCES)
    except AuthException:
        await ws.close(code=4401)
        return
    await handle_detection_socket(ws, claims.user_id)
