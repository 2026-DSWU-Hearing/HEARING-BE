"""소리 필터링의 핵심 서비스.

흐름:
  1) 활성 모드 조회 (Mode.is_active=True)
  2) 활성 모드의 ModeSound 목록과 감지된 sound_id 대조
  3) 매칭 안되면 → 무시 (DB 저장하지 않음)
  4) 매칭되면 → Notification 저장 + FCM push + WS broadcast
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.functions import get_or_404
from app.models.device import Device
from app.models.mode import Mode, ModeSound
from app.models.notification import Notification
from app.models.user import User
from app.schemas.device import DetectionCreate


async def handle_detection(
    db: AsyncSession,
    user_id: int,
    device: Device,
    payload: DetectionCreate,
    source: str,
) -> Notification | None:
    from app.services import location_service, push_service
    from app.websocket import detection_handler

    active_sound_ids = await _get_active_mode_sound_ids(db, user_id)
    if active_sound_ids is None:
        logger.info("no active mode for user_id=%s, skip", user_id)
        return None

    if payload.sound_id is None or payload.sound_id not in active_sound_ids:
        logger.info(
            "sound_id=%s not in active mode (user=%s), skip",
            payload.sound_id, user_id,
        )
        return None

    location = None
    if payload.latitude is not None and payload.longitude is not None:
        location = await location_service.reverse_geocode(payload.latitude, payload.longitude)

    notification = Notification(
        user_id=user_id,
        device_id=device.id,
        sound_id=payload.sound_id,
        sound_name=payload.sound_name,
        sound_category=payload.sound_category,
        risk_level=payload.risk_level,
        source=source,
        confidence=payload.confidence,
        location=location,
        detected_at=payload.detected_at,
        is_read=False,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    user = await get_or_404(db, User, user_id)
    if not user.do_not_disturb and user.fcm_token:
        await push_service.send_detection_push(user.fcm_token, notification)

    await detection_handler.broadcast_detection(user_id, notification)
    return notification


async def _get_active_mode_sound_ids(db: AsyncSession, user_id: int) -> set[int] | None:
    result = await db.execute(
        select(ModeSound.sound_id)
        .join(Mode, Mode.id == ModeSound.mode_id)
        .where(Mode.user_id == user_id, Mode.is_active.is_(True))
    )
    rows = list(result.scalars().all())
    if not rows:
        return None
    return set(rows)


async def list_notifications(
    db: AsyncSession, user_id: int, page: int = 1, size: int = 30
) -> list[Notification]:
    from app.db.functions import apply_pagination

    q = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.detected_at.desc())
    )
    result = await db.execute(apply_pagination(q, page, size))
    return list(result.scalars().all())


async def mark_read(db: AsyncSession, user_id: int, notification_id: int) -> Notification:
    from app.core.exceptions import ForbiddenException

    notif = await get_or_404(db, Notification, notification_id)
    if notif.user_id != user_id:
        raise ForbiddenException("Not your notification")
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return notif


async def delete_notification(db: AsyncSession, user_id: int, notification_id: int) -> None:
    from app.core.exceptions import ForbiddenException

    notif = await get_or_404(db, Notification, notification_id)
    if notif.user_id != user_id:
        raise ForbiddenException("Not your notification")
    await db.delete(notif)
    await db.commit()
