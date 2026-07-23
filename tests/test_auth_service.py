"""auth_service 유닛테스트 — 구글/게스트 로그인, 토큰 재발급, 데모 시드.

verify_google_id_token 은 구글 공개키 네트워크 호출이라 monkeypatch 로 대체한다.
"""

import pytest
from sqlalchemy import func, select

from app.core.exceptions import AuthException
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.device import Device
from app.models.mode import Mode
from app.models.notification import Notification
from app.models.sound import Sound, SoundCategory
from app.models.user import User
from app.schemas.auth import GoogleLoginRequest
from app.services import auth_service


async def _count(db, model) -> int:
    result = await db.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def _assert_login_left_devices_alone(db, user_id: int) -> None:
    """로그인은 기기를 건드리지 않는다 — 행 생성도, 현재 사용자(active_user) 전환도 없다.
    (물리 기기 행은 기동/조회 경로의 ensure 소관이고, 전환은 오직 POST /devices/connect 에서만)"""
    devices = (await db.execute(select(Device))).scalars().all()
    assert all(d.active_user_id != user_id for d in devices)
    assert len(devices) <= 1  # 로그인 경로가 행을 늘렸다면 단일 행 모델이 깨진 것


def _fake_google(sub: str, email: str, name: str = "구글유저"):
    async def _verify(id_token: str) -> dict:
        return {"sub": sub, "email": email, "name": name}
    return _verify


@pytest.mark.asyncio
async def test_google_login_creates_new_user(db, monkeypatch):
    monkeypatch.setattr(auth_service, "verify_google_id_token", _fake_google("g-123", "new@gmail.com"))

    tokens = await auth_service.google_login(db, GoogleLoginRequest(id_token="x"))

    assert tokens.access_token and tokens.refresh_token
    user = (await db.execute(select(User).where(User.google_sub == "g-123"))).scalar_one()
    assert user.email == "new@gmail.com"
    assert user.is_google_user is True
    assert user.terms_agreed is False  # 약관은 별도 동의로만 True
    assert user.push_enabled is False
    await _assert_login_left_devices_alone(db, user.id)


@pytest.mark.asyncio
async def test_google_login_reuses_existing_user(db, monkeypatch):
    db.add(User(
        email="dup@gmail.com",
        nickname="기존",
        is_google_user=True,
        google_sub="g-123",
        push_enabled=True,
    ))
    await db.commit()
    monkeypatch.setattr(auth_service, "verify_google_id_token", _fake_google("g-123", "dup@gmail.com"))

    await auth_service.google_login(db, GoogleLoginRequest(id_token="x"))

    assert await _count(db, User) == 1  # 새 유저를 만들지 않고 재사용
    user = (await db.execute(select(User))).scalars().one()
    assert user.push_enabled is True
    await _assert_login_left_devices_alone(db, user.id)


@pytest.mark.asyncio
async def test_guest_login_without_catalog_still_creates_user(db):
    tokens = await auth_service.guest_login(db)

    assert tokens.access_token
    user = (await db.execute(select(User))).scalars().one()
    assert user.nickname == "게스트"
    assert user.email.endswith("@demo.hearing.local")
    assert user.terms_agreed is True
    assert user.push_enabled is False
    await _assert_login_left_devices_alone(db, user.id)
    assert await _count(db, Mode) == 0
    assert await _count(db, Notification) == 0


@pytest.mark.asyncio
async def test_guest_login_seeds_demo_data_when_catalog_present(db):
    db.add(SoundCategory(id=1, name="긴급"))
    await db.flush()
    demo_sounds = {n for _, _, names, _ in auth_service._DEMO_MODES for n in names}
    for i, name in enumerate(sorted(demo_sounds), start=1):
        db.add(Sound(id=i, name=name, category_id=1))
    await db.commit()

    await auth_service.guest_login(db)

    user = (await db.execute(select(User))).scalars().one()
    await _assert_login_left_devices_alone(db, user.id)
    assert await _count(db, Mode) == len(auth_service._DEMO_MODES)
    assert await _count(db, Notification) == len(auth_service._DEMO_NOTIFICATIONS)


@pytest.mark.asyncio
async def test_refresh_tokens_issues_new_pair(db):
    refresh = create_refresh_token(7)

    tokens = await auth_service.refresh_tokens(refresh)

    assert tokens.token_type == "bearer"
    assert decode_token(tokens.access_token)["sub"] == "7"


@pytest.mark.asyncio
async def test_refresh_tokens_rejects_access_token(db):
    access = create_access_token(7, source="user")

    with pytest.raises(AuthException):
        await auth_service.refresh_tokens(access)


# --- 로그아웃 = refresh 블랙리스트 (Redis) ---


@pytest.mark.asyncio
async def test_logout_blacklists_refresh_token(test_redis):
    refresh = create_refresh_token(7)
    assert (await auth_service.refresh_tokens(refresh)).access_token  # 로그아웃 전엔 재발급됨

    await auth_service.logout(refresh)

    with pytest.raises(AuthException, match="revoked"):
        await auth_service.refresh_tokens(refresh)


@pytest.mark.asyncio
async def test_logout_ignores_invalid_token(test_redis):
    await auth_service.logout("garbage-token")  # 예외 없이 조용히 무시돼야 한다


@pytest.mark.asyncio
async def test_refresh_fail_open_when_redis_down(monkeypatch):
    """Redis 가 죽으면 블랙리스트 확인만 건너뛰고 재발급은 정상 동작한다."""

    class DeadRedis:
        def __getattr__(self, name):
            async def _fail(*args, **kwargs):
                raise ConnectionError("redis down")
            return _fail

    monkeypatch.setattr(auth_service, "get_redis", lambda: DeadRedis())

    tokens = await auth_service.refresh_tokens(create_refresh_token(7))
    assert tokens.access_token
    await auth_service.logout(create_refresh_token(7))  # 로그아웃도 예외 없이 통과


@pytest.mark.asyncio
async def test_logout_endpoint_revokes_refresh(api_client, test_redis):
    """엔드포인트 관통: 게스트 로그인 → 로그아웃(body에 refresh) → 재발급 401."""
    client, _ = api_client
    tokens = (await client.post("/auth/guest")).json()

    r = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200, r.text

    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401, r.text
