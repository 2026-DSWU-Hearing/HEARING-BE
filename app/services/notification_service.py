"""소리 필터링의 핵심 서비스.

흐름:
  1) 활성 모드 조회 (Mode.is_active=True)
  2) 활성 모드의 ModeSound 목록과 감지된 소리 대조
     - sound_id 가 오면 그대로, AI서버처럼 한글 (category, name)만 오면 이름으로 해석
  3) 매칭 안되면 → 무시 (DB 저장하지 않음)
  4) 매칭되면 → Notification 저장 + FCM push + WS broadcast + 기기 진동 명령
"""

import base64
import binascii
from datetime import datetime

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.core.logger import logger
from app.db.functions import get_or_404, get_owned_or_403
from app.models.device import Device
from app.models.mode import Mode, ModeSound
from app.models.notification import Notification
from app.models.sound import Sound, SoundCategory
from app.models.user import User
from app.schemas.device import DetectionCreate
from app.schemas.notification import NotificationItem, NotificationListResponse


async def handle_detection(
    db: AsyncSession,
    user_id: int,
    device: Device,
    payload: DetectionCreate,
    source: str,
) -> Notification | None:
    from app.services import push_service
    from app.websocket import detection_handler, device_handler

    # 방해금지(완전 차단): 켜져 있으면 감지를 통째로 무시한다.
    # 기록(DB)·WS 인앱 알림·FCM 푸시 전부 중단 (앱 푸시 OFF 와 달리 기록도 남기지 않음).
    user = await get_or_404(db, User, user_id)
    if user.do_not_disturb:
        logger.info("do-not-disturb on, skip detection user_id=%s", user_id)
        return None

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

    # confidence 없이도 감지는 저장한다(화재 경보를 메타데이터 하나 때문에 잃지 않는다).
    # 다만 조용히 넘기면 프로듀서 버그를 못 잡으므로 로그로 드러낸다.
    if payload.confidence is None:
        logger.warning(
            "detection without confidence: source=%s user_id=%s sound=%s/%s",
            source, user_id, payload.sound_category, payload.sound_name,
        )

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

    if user.push_enabled and user.fcm_token:  # do_not_disturb 는 위에서 이미 차단됨
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

    # 하드웨어 진동 명령 — do_not_disturb·모드 매칭은 위에서 이미 통과했다.
    # 기기 WS 가 끊겨 있으면 드롭 (진동은 실시간 경보라 큐잉하지 않음). 연결은 MAC 단위.
    await device_handler.send_vibrate(
        mac=device.mac_address,
        strength=user.haptic_strength,
        sound_name=notification.sound_name,
        sound_category=notification.sound_category,
        direction=payload.direction,
    )
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


LIST_LIMIT_DEFAULT = 20
LIST_LIMIT_MIN = 1
LIST_LIMIT_MAX = 50


def _encode_cursor(notification: Notification) -> str:
    """(detected_at, id) 를 불투명 문자열로. FE 는 내용을 해석하지 않고 그대로 돌려주므로
    형식은 서버 자유다."""
    raw = f"{notification.detected_at.isoformat()}|{notification.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        detected_at_raw, id_raw = raw.rsplit("|", 1)
        detected_at = datetime.fromisoformat(detected_at_raw)
        notification_id = int(id_raw)
    except (ValueError, TypeError, binascii.Error) as e:
        raise ValidationException("Invalid cursor") from e
    # 타임존이 없으면 timestamptz 비교가 UTC 로 간주돼 9시간 어긋난 지점부터 잘린다.
    if detected_at.tzinfo is None:
        raise ValidationException("Invalid cursor")
    return detected_at, notification_id


async def list_notifications(
    db: AsyncSession,
    user_id: int,
    cursor: str | None = None,
    limit: int = LIST_LIMIT_DEFAULT,
) -> NotificationListResponse:
    """내 알림을 최신순으로. 커서 기반 무한 스크롤.

    커서는 반드시 (detected_at, id) 튜플이다. detected_at 단독으로 자르면 같은 초에 잡힌
    감지들이 통째로 누락되거나(`<`) 무한 중복되고(`<=`), id 단독으로 자르면 넥밴드가
    오프라인 중 버퍼링했다 늦게 올린 감지에서 id 순서와 시간 순서가 어긋나 항목이 건너뛰어진다.

    limit 은 범위를 벗어나도 400 을 내지 않고 잘라낸다 — 무한 스크롤 도중 400 이 나면
    화면이 이유 없이 멈춘다.
    """
    limit = max(LIST_LIMIT_MIN, min(limit, LIST_LIMIT_MAX))

    q = select(Notification).where(Notification.user_id == user_id)
    if cursor:
        cursor_detected_at, cursor_id = _decode_cursor(cursor)
        q = q.where(
            tuple_(Notification.detected_at, Notification.id)
            < tuple_(cursor_detected_at, cursor_id)
        )
    # 한 건 더 읽어 다음 페이지 존재 여부를 별도 count 쿼리 없이 판단한다.
    q = q.order_by(Notification.detected_at.desc(), Notification.id.desc()).limit(limit + 1)

    rows = list((await db.execute(q)).scalars().all())
    has_next = len(rows) > limit
    items = rows[:limit]
    return NotificationListResponse(
        items=[NotificationItem.model_validate(row) for row in items],
        next_cursor=_encode_cursor(items[-1]) if has_next else None,
        has_next=has_next,
    )


async def delete_notifications(db: AsyncSession, user_id: int, ids: list[int]) -> int:
    """선택 삭제. **멱등** — 없는 id·이미 지운 id·남의 id 가 섞여도 404·403 을 내지 않고
    조용히 건너뛴다.

    이유 둘: 사용자가 삭제 모드에서 고르는 사이 WS 로 목록이 갱신되거나 다른 세션에서 이미
    지웠을 수 있어서, 그때 에러를 띄우면 '지우려던 게 이미 없는데 실패했다'는 무의미한 실패가
    된다. 그리고 남의 id 에 403 을 주면 id 존재 여부가 새어 나간다(enumeration).

    user_id 조건이 소유권 검사를 겸한다 — 남의 행은 WHERE 에 걸리지 않아 애초에 안 지워진다.
    """
    result = await db.execute(
        delete(Notification).where(
            Notification.user_id == user_id,
            Notification.id.in_(set(ids)),  # 중복은 서버가 제거
        )
    )
    await db.commit()
    return result.rowcount
