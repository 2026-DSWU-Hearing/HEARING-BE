import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthException
from app.core.logger import logger
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_google_id_token,
)
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
        # terms_agreed 는 기본 False — 실제 약관 동의(PATCH /users/me/agreement)로만 True 가 된다.
        # (게스트는 데모 편의상 True 유지)
        user = User(
            email=info["email"],
            nickname=info.get("name", info["email"].split("@")[0]),
            is_google_user=True,
            google_sub=info["sub"],
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        # 신규 계정에만 기본 모드(가정/긴급/외출)를 시드한다 — 활성 모드가 있어야 감지 흐름이
        # 동작하므로 첫 로그인부터 바로 쓸 수 있게. 데모 알림(_seed_demo_notifications)은
        # 게스트 전용이라 실계정엔 넣지 않는다(가짜 감지 기록 방지). 재로그인 시엔 이 분기를
        # 타지 않으므로 중복 시드도 없다.
        await _seed_default_modes(db, user.id)
    return _issue_tokens(user.id)


# --- 신규 가입 기본 시드 --------------------------------------------------------
# 새 계정(게스트 + 구글 첫 로그인)에 기본 모드를 깔아 첫 화면이 비지 않게 하고, 활성 모드가
# 있어야 감지 흐름이 동작하므로 최소 1개를 활성으로 둔다. 모드 시드는 두 로그인이 공유한다.
# 게스트는 추가로 데모용 가짜 알림까지 채운다(리뷰어가 알림 화면을 바로 보게) — 실계정엔 안 넣음.
# 게스트는 email 도메인(@demo.hearing.local)으로 식별 → 추후 일괄 정리 가능.

_GUEST_EMAIL_DOMAIN = "demo.hearing.local"

# (모드명, 아이콘, [소리이름], 활성여부) — 소리는 이름으로 조회(시드 순서와 무관하게).
# 아이콘은 반드시 mode_icons.py 의 icon_key(ic_*) 값. FE 아이콘 매핑이 ic_* 만 인식하므로
# 'home' 처럼 접두사 없는 값을 넣으면 UnknownModeIcon 으로 떨어져 아이콘이 안 뜬다.
# 소리 이름도 카탈로그(Sound.name)와 정확히 일치해야 함('노크'가 아니라 '노크 소리').
_DEFAULT_MODES: list[tuple[str, str, list[str], bool]] = [
    ("가정", "ic_home", ["가전제품"], True),
    ("긴급", "ic_emergency", ["경적"], False),
    ("외출", "ic_goingOut", ["노크 소리"], False),
]
# (소리이름, 카테고리) — 게스트 전용 데모 알림. 알림 화면이 비어 보이지 않게 최근 몇 건 시드.
# 실사용자(구글) 계정엔 넣지 않는다: 실제로 발생하지 않은 감지 기록은 오해를 준다.
# 기기는 사용자가 직접 등록하는 흐름이라 시드 시점엔 없다 → device_id=None (SET NULL 계약).
_DEMO_NOTIFICATIONS: list[tuple[str, str]] = [
    ("경적", "교통"),
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
    await _seed_default_modes(db, user.id)
    await _seed_demo_notifications(db, user.id)
    return _issue_tokens(user.id)


async def _seed_default_modes(db: AsyncSession, user_id: int) -> None:
    """새 계정에 기본 모드(가정/긴급/외출)를 만든다. 게스트/구글 첫 로그인이 공유한다.
    활성 모드가 있어야 감지 흐름이 동작하므로 최소 1개를 활성으로 둔다.
    소리 카탈로그가 아직 시드되지 않은 환경이면 조용히 건너뛴다(로그인 자체는 정상)."""
    wanted = {name for _, _, names, _ in _DEFAULT_MODES for name in names}
    rows = await db.execute(select(Sound.name, Sound.id).where(Sound.name.in_(wanted)))
    sound_id_by_name = {name: sid for name, sid in rows.all()}
    if not sound_id_by_name:
        return

    for name, icon, sound_names, is_active in _DEFAULT_MODES:
        sound_ids = [sound_id_by_name[n] for n in sound_names if n in sound_id_by_name]
        if not sound_ids:
            continue
        mode = Mode(user_id=user_id, name=name, icon=icon, is_active=is_active)
        for sid in sound_ids:
            mode.sound_links.append(ModeSound(sound_id=sid))
        db.add(mode)
    await db.commit()


async def _seed_demo_notifications(db: AsyncSession, user_id: int) -> None:
    """게스트 전용: 알림 화면이 비어 보이지 않게 최근 알림 몇 건을 시드한다.
    실사용자(구글) 계정엔 호출하지 않는다(가짜 감지 기록 방지).
    소리 카탈로그가 없으면 sound_id 는 None 으로 남지만 알림 자체는 표시된다."""
    names = [name for name, _ in _DEMO_NOTIFICATIONS]
    rows = await db.execute(select(Sound.name, Sound.id).where(Sound.name.in_(names)))
    sound_id_by_name = {name: sid for name, sid in rows.all()}

    now = datetime.now(timezone.utc)
    for i, (sound_name, category) in enumerate(_DEMO_NOTIFICATIONS, start=1):
        db.add(
            Notification(
                user_id=user_id,
                device_id=None,
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


async def refresh_tokens(refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthException("Invalid refresh token")
    if await _is_refresh_blacklisted(refresh_token):
        raise AuthException("Refresh token revoked")
    return _issue_tokens(int(payload["sub"]))


# --- 로그아웃 = refresh 토큰 무효화 (Redis 블랙리스트) --------------------------
# JWT 는 stateless 라 서버가 못 지우므로, 로그아웃된 refresh 토큰을 남은 수명만큼
# Redis 에 올려 재발급을 차단한다(TTL 이 지나면 토큰도 만료라 자동 소멸).
# Redis 다운 시 fail-open: 차단만 안 될 뿐 로그인/재발급/로그아웃 자체는 정상(경고 로그).


def _refresh_blacklist_key(refresh_token: str) -> str:
    # 원문 토큰을 Redis 에 남기지 않도록 해시로 키를 만든다
    return "bl:refresh:" + hashlib.sha256(refresh_token.encode()).hexdigest()


async def logout(refresh_token: str) -> None:
    """refresh 토큰을 남은 수명만큼 블랙리스트에 올린다.
    불량/만료 토큰은 조용히 무시 — 로그아웃은 항상 성공해야 한다."""
    try:
        payload = decode_token(refresh_token)
    except AuthException:
        return
    if payload.get("type") != "refresh":
        return
    ttl = int(payload["exp"] - datetime.now(timezone.utc).timestamp())
    if ttl <= 0:
        return
    try:
        await get_redis().set(_refresh_blacklist_key(refresh_token), "1", ex=ttl)
    except Exception as e:
        logger.warning("logout blacklist skipped (redis unavailable): %s", e)


async def _is_refresh_blacklisted(refresh_token: str) -> bool:
    try:
        return await get_redis().exists(_refresh_blacklist_key(refresh_token)) == 1
    except Exception as e:
        logger.warning("blacklist check skipped (redis unavailable): %s", e)
        return False


def _issue_tokens(user_id: int) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id, source="user"),
        refresh_token=create_refresh_token(user_id),
    )
