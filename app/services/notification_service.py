"""소리 필터링의 핵심 서비스.

흐름:
  1) 활성 모드 조회 (Mode.is_active=True)
  2) 활성 모드의 ModeSound 목록과 감지된 소리 대조
     - sound_id 가 오면 그대로, AI서버처럼 한글 (category, name)만 오면 이름으로 해석
  3) 매칭 안되면 → 무시 (DB 저장하지 않음)
  4) 매칭되면 → Notification 저장 + FCM push + WS broadcast
"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.functions import apply_pagination, get_or_404, get_owned_or_403
from app.models.device import Device
from app.models.mode import Mode, ModeSound
from app.models.notification import Notification
from app.models.sound import Sound, SoundCategory
from app.models.user import User
from app.schemas.device import DetectionCreate


async def handle_detection(
    db: AsyncSession,
    user_id: int,
    device: Device,
    payload: DetectionCreate,
    source: str,
) -> Notification | None:
    from app.services import push_service
    from app.websocket import detection_handler

    active_sound_ids = await _get_active_mode_sound_ids(db, user_id)
    if active_sound_ids is None:
        logger.info("no active mode for user_id=%s, skip", user_id)
        return None

    # AI서버는 sound_id 를 모르고 한글 (category, name)만 보낸다 → 이름으로 sound_id 해석.
    # 웨어러블이 sound_id 를 직접 주면 그대로 사용.
    sound_id = payload.sound_id
    if sound_id is None:
        sound_id = await _resolve_sound_id(db, payload.sound_category, payload.sound_name)

    if sound_id is None or sound_id not in active_sound_ids:
        logger.info(
            "sound not in active mode (user=%s, id=%s, %s/%s), skip",
            user_id, sound_id, payload.sound_category, payload.sound_name,
        )
        return None

    location = None  # 역지오코딩(location_service) 보류 — payload 좌표는 아직 사용 안 함

    notification = Notification(
        user_id=user_id,
        device_id=device.id,
        sound_id=sound_id,
        sound_name=payload.sound_name,
        sound_category=payload.sound_category,
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
        fcm_token = user.fcm_token
        try:
            await push_service.send_detection_push(fcm_token, notification)
        except push_service.UnregisteredFcmTokenError:
            result = await db.execute(
                update(User)
                .where(User.id == user_id, User.fcm_token == fcm_token)
                .values(fcm_token=None)
            )
            await db.commit()
            if result.rowcount:
                logger.info("removed unregistered FCM token for user_id=%s", user_id)

    await detection_handler.broadcast_detection(user_id, notification)
    return notification


async def _resolve_sound_id(db: AsyncSession, category_name: str, sound_name: str) -> int | None:
    """한글 (카테고리, 소리이름) → Sound.id. AI서버 감지 결과 매칭용.

    소리이름은 카테고리 간 중복될 수 있어('충돌·파손음'은 긴급/생활음 둘 다 존재)
    반드시 카테고리까지 함께 본다. AI의 category_map.py 한글 이름과 시드 카탈로그가 일치하므로
    이름만으로 안전하게 해석된다.
    """
    result = await db.execute(
        select(Sound.id)
        .join(SoundCategory, Sound.category_id == SoundCategory.id)
        .where(Sound.name == sound_name, SoundCategory.name == category_name)
    )
    return result.scalar_one_or_none()


async def _get_active_mode_sound_ids(db: AsyncSession, user_id: int) -> set[int] | None:
    result = await db.execute(
        select(ModeSound.sound_id)
        .join(Mode, Mode.id == ModeSound.mode_id)
        .where(Mode.user_id == user_id, Mode.is_active.is_(True), ModeSound.is_active.is_(True))
    )
    rows = list(result.scalars().all())
    if not rows:
        return None
    return set(rows)


async def list_notifications(
    db: AsyncSession, user_id: int, page: int = 1, size: int = 30
) -> list[Notification]:
    q = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.detected_at.desc())
    )
    result = await db.execute(apply_pagination(q, page, size))
    return list(result.scalars().all())


async def mark_read(db: AsyncSession, user_id: int, notification_id: int) -> Notification:
    notif = await get_owned_or_403(db, Notification, notification_id, user_id)
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return notif


async def delete_notification(db: AsyncSession, user_id: int, notification_id: int) -> None:
    notif = await get_owned_or_403(db, Notification, notification_id, user_id)
    await db.delete(notif)
    await db.commit()
