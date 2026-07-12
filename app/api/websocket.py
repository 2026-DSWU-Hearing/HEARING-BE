from fastapi import APIRouter, Query, WebSocket

from app.core.exceptions import AuthException
from app.core.security import DEVICE_WS_SOURCES, USER_ACCESS_SOURCES, decode_access_token
from app.websocket import device_handler
from app.websocket.detection_handler import handle_detection_socket

router = APIRouter()


async def _reject(ws: WebSocket, code: int) -> None:
    """핸드셰이크를 수락한 직후 지정 코드로 닫는다.
    accept 전에 close 하면 uvicorn 이 HTTP 403 으로 핸드셰이크를 거부해서
    실제 클라이언트(브라우저·ESP32)는 close 코드를 영영 못 받는다."""
    await ws.accept()
    await ws.close(code=code)


@router.websocket("/ws/users/me/detections")
async def ws_detections(ws: WebSocket, token: str = Query(...)):
    try:
        claims = decode_access_token(token, USER_ACCESS_SOURCES)
    except AuthException:
        await _reject(ws, 4401)
        return
    await handle_detection_socket(ws, claims.user_id)


@router.websocket("/ws/devices")
async def ws_devices(ws: WebSocket, token: str = Query(...), mac: str = Query(...)):
    """하드웨어(ESP32) 상태/명령 채널. token 은 정품 기기 증명, 기기 선택은 MAC."""
    try:
        decode_access_token(token, DEVICE_WS_SOURCES)
    except AuthException:
        await _reject(ws, 4401)
        return
    device_id = await device_handler.resolve_device_id(mac)
    if device_id is None:
        await _reject(ws, 4404)  # 미등록 MAC
        return
    await device_handler.handle_device_socket(ws, device_id)
