"""실시간 소리 감지 WS 핸들러. /ws/users/me/detections."""

from fastapi import WebSocket, WebSocketDisconnect

from app.core.logger import logger
from app.models.notification import Notification
from app.schemas.notification import NotificationItem
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
    """notification_service가 호출. 매칭된 감지결과를 해당 유저 WS로 push.

    data 는 GET /notifications 의 items 와 **같은 스키마**로 직렬화한다. FE 가 이 이벤트를
    목록 캐시에 그대로 끼워 넣기 때문에 두 경로가 갈라지면 중복·누락이 생긴다.
    여기서 dict 를 손으로 만들면 목록 응답과 언젠가 어긋나므로 모델을 거친다."""
    payload = {
        "type": "detection",
        # id 는 db.refresh 로 확정된 PK — FE 는 이 id 를 그대로 삭제 요청에 싣는다.
        "data": NotificationItem.model_validate(notification).model_dump(mode="json"),
    }
    await manager.send_to_user(user_id, payload)
