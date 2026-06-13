"""실시간 소리 감지 WS 핸들러. /ws/users/me/detections."""

from fastapi import WebSocket, WebSocketDisconnect

from app.core.logger import logger
from app.models.notification import Notification
from app.websocket.manager import manager


async def handle_detection_socket(ws: WebSocket, user_id: int) -> None:
    await manager.connect(user_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, ws)
    except Exception as e:
        logger.error("detection ws error user=%s: %s", user_id, e)
        manager.disconnect(user_id, ws)


async def broadcast_detection(user_id: int, notification: Notification) -> None:
    """notification_service가 호출. 매칭된 감지결과를 해당 유저 WS로 push."""
    payload = {
        "type": "detection",
        "data": {
            "id": notification.id,
            "sound_name": notification.sound_name,
            "sound_category": notification.sound_category,
            "source": notification.source,
            "confidence": notification.confidence,
            "location": notification.location,
            "detected_at": notification.detected_at.isoformat(),
        },
    }
    await manager.send_to_user(user_id, payload)
