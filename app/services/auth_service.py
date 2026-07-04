import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_google_id_token,
)
from app.models.device import Device
from app.models.mode import Mode, ModeSound
from app.models.notification import Notification
from app.models.sound import Sound
from app.models.user import User
from app.schemas.auth import GoogleLoginRequest, TokenResponse


async def google_login(db: AsyncSession, payload: GoogleLoginRequest) -> TokenResponse:
    info = await verify_google_id_token(payload.id_token)
    result = await db.execute(select(User).where(User.google_sub == info["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            email=info["email"],
            nickname=info.get("name", info["email"].split("@")[0]),
            is_google_user=True,
            google_sub=info["sub"],
            terms_agreed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return _issue_tokens(user.id)


# --- 게스트(데모) 로그인 -------------------------------------------------------
# 포트폴리오 데모용: 방문자(리뷰어)가 구글 계정 연동 없이 원클릭으로 둘러볼 수 있게 한다.
# 매 호출마다 독립 게스트 유저 + 샘플 데이터를 만들어 리뷰어끼리 데이터가 섞이지 않는다.
# 게스트는 email 도메인(@demo.hearing.local)으로 식별 → 추후 일괄 정리 가능.

_GUEST_EMAIL_DOMAIN = "demo.hearing.local"

# (모드명, 아이콘, [소리이름], 활성여부) — 소리는 이름으로 조회(시드 순서와 무관하게).
_DEMO_MODES: list[tuple[str, str, list[str], bool]] = [
    ("외출", "walk", ["사이렌", "경적", "자동차 경고음"], True),
    ("가정", "home", ["화재 경보", "노크 소리", "개"], False),
]
# (소리이름, 카테고리) — 알림 화면이 비어 보이지 않게 최근 알림 몇 건 시드.
_DEMO_NOTIFICATIONS: list[tuple[str, str]] = [
    ("사이렌", "긴급"),
    ("노크 소리", "생활음"),
]


async def guest_login(db: AsyncSession) -> TokenResponse:
    user = User(
        email=f"guest-{uuid.uuid4().hex[:12]}@{_GUEST_EMAIL_DOMAIN}",
        nickname="게스트",
        terms_agreed=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await _seed_demo_data(db, user.id)
    return _issue_tokens(user.id)


async def _seed_demo_data(db: AsyncSession, user_id: int) -> None:
    """게스트에게 샘플 모드/디바이스/알림을 채워 화면이 비어 보이지 않게 한다.
    소리 카탈로그가 아직 시드되지 않은 환경이면 조용히 건너뛴다(로그인 자체는 정상)."""
    wanted = {name for _, _, names, _ in _DEMO_MODES for name in names}
    rows = await db.execute(select(Sound.name, Sound.id).where(Sound.name.in_(wanted)))
    sound_id_by_name = {name: sid for name, sid in rows.all()}
    if not sound_id_by_name:
        return

    device = Device(
        user_id=user_id,
        nickname="데모 디바이스",
        mac_address=_random_mac(),
        is_connected=True,
    )
    db.add(device)

    for name, icon, sound_names, is_active in _DEMO_MODES:
        sound_ids = [sound_id_by_name[n] for n in sound_names if n in sound_id_by_name]
        if not sound_ids:
            continue
        mode = Mode(user_id=user_id, name=name, icon=icon, is_active=is_active)
        for sid in sound_ids:
            mode.sound_links.append(ModeSound(sound_id=sid))
        db.add(mode)

    await db.flush()  # device.id 확보

    now = datetime.now(timezone.utc)
    for i, (sound_name, category) in enumerate(_DEMO_NOTIFICATIONS, start=1):
        db.add(
            Notification(
                user_id=user_id,
                device_id=device.id,
                sound_id=sound_id_by_name.get(sound_name),
                sound_name=sound_name,
                sound_category=category,
                source="ai-server",
                confidence=0.95,
                detected_at=now - timedelta(minutes=5 * i),
                is_read=False,
            )
        )
    await db.commit()


def _random_mac() -> str:
    h = uuid.uuid4().hex[:12]
    return ":".join(h[i : i + 2] for i in range(0, 12, 2)).upper()


async def refresh_tokens(refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthException("Invalid refresh token")
    return _issue_tokens(int(payload["sub"]))


def _issue_tokens(user_id: int) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id, source="user"),
        refresh_token=create_refresh_token(user_id),
    )
