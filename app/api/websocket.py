from fastapi import APIRouter, Depends, Query, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthException
from app.core.security import decode_token
from app.db.dependencies import get_db
from app.websocket.detection_handler import handle_detection_socket
from app.websocket.stt_handler import handle_stt_socket

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


@router.websocket("/ws/conversations/{conv_id}/stt")
async def ws_stt(ws: WebSocket, conv_id: int, token: str = Query(...), db: AsyncSession = Depends(get_db)):
    try:
        _user_id_from_token(token)
    except AuthException:
        await ws.close(code=4401)
        return
    await handle_stt_socket(ws, conv_id, db)
