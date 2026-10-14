"""실시간 소리 감지 WS 핸들러. /ws/users/me/detections."""

from fastapi import WebSocket, WebSocketDisconnect

from app.core.logger import logger
from app.models.mode import Mode
from app.models.notification import Notification
from app.schemas.device import DetectionCreate
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


async def broadcast_filtered(user_id: int, payload: DetectionCreate, reason: str) -> None:
    """모드에 걸러진 감지를 같은 채널로 알린다 — 시연 대시보드가 "서버까지 왔지만 모드에 없어 버려짐"
    장면을 보여주기 위한 것. **DB 저장 없음** — 알림 목록(GET /notifications)엔 뜨지 않는다.

    reason: "no_active_mode" (활성 모드 없음) | "not_in_mode" (활성 모드에 이 소리가 없음)
    앱(HEARING-FE)은 type 을 보고 "detection" 만 처리하므로 이 메시지는 무시된다.
    """
    await manager.send_to_user(user_id, {
        "type": "detection_filtered",
        "data": {
            "sound_name": payload.sound_name,
            "sound_category": payload.sound_category,
            "confidence": payload.confidence,
            "direction": payload.direction,
            "ondevice_vibrated": payload.ondevice_vibrated,
            "detected_at": payload.detected_at.isoformat(),
            "reason": reason,
        },
    })


async def broadcast_mode_changed(user_id: int, mode: Mode) -> None:
    """활성 모드가 바뀌었음을 알린다 (PATCH /modes/{id}/activate). 대시보드가 폴링을 기다리지 않고
    현재 모드를 즉시 바꾸는 용도. 앱은 type 분기로 무시한다."""
    await manager.send_to_user(user_id, {
        "type": "mode_changed",
        "data": {"mode_id": mode.id, "name": mode.name, "is_active": True},
    })
