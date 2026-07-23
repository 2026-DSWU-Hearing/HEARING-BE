"""[기기 연결] 흐름 — 물리 기기 1행 + active_user 전환 계약.

핵심 계약:
  - connect 는 하드웨어 WS 접속 여부를 즉시 확인 (미접속 409, 폴링 없음)
  - 성공 시 요청 계정이 현재 사용자(active user)가 된다 — 덮어쓰기 전환
  - 기기 이름은 계정별(users.device_nickname), 응답은 항상 요청 계정 기준 뷰
  - GET /devices 는 항상 길이 1 (행이 없으면 ensure 가 자가 치유)
"""

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User
from app.services.device_service import DEFAULT_DEVICE_NICKNAME, THE_DEVICE_ID
from app.websocket.manager import device_manager


class FakeWebSocket:
    async def accept(self):
        pass

    async def send_json(self, message):
        pass

    async def close(self, code=1000):
        pass


@pytest_asyncio.fixture
async def hardware_online():
    """실물 하드웨어가 서버 WS 에 붙어 있는 상태를 흉내낸다 (런타임 레지스트리만 — DB 는 각 테스트 관심사 아님)."""
    ws = FakeWebSocket()
    await device_manager.connect(settings.DEVICE_MAC_ADDRESS, ws)
    yield ws
    device_manager.disconnect(settings.DEVICE_MAC_ADDRESS, ws)


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, source="user")}


async def _seed_users(session_factory) -> None:
    async with session_factory() as db:
        db.add_all([
            User(id=1, email="first@t.local", nickname="first", terms_agreed=True),
            User(id=2, email="second@t.local", nickname="second", terms_agreed=True),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_get_devices_always_returns_the_single_device(api_client):
    """기기 행을 시드하지 않아도 조회가 성공해야 한다 — ensure 의 자가 치유 검증."""
    client, session_factory = api_client
    await _seed_users(session_factory)

    r = await client.get("/devices", headers=_auth(1))

    assert r.status_code == 200, r.text
    devices = r.json()
    assert len(devices) == 1
    assert devices[0]["id"] == THE_DEVICE_ID
    assert devices[0]["nickname"] == DEFAULT_DEVICE_NICKNAME
    assert devices[0]["is_active_user"] is False
    assert devices[0]["is_connected"] is False


@pytest.mark.asyncio
async def test_connect_fails_fast_when_hardware_offline(api_client):
    """하드웨어 미접속이면 즉시 409 — 온보딩이 30초 기다릴 필요가 없다. 전환도 일어나지 않는다."""
    client, session_factory = api_client
    await _seed_users(session_factory)

    r = await client.post("/devices/connect", headers=_auth(1), json={"nickname": "내 목걸이"})

    assert r.status_code == 409, r.text
    assert "기기가 서버에 연결되어 있지 않습니다" in r.json()["message"]
    r = await client.get("/devices", headers=_auth(1))
    assert r.json()[0]["is_active_user"] is False


@pytest.mark.asyncio
async def test_connect_switches_active_user_and_saves_nickname(api_client, hardware_online):
    client, session_factory = api_client
    await _seed_users(session_factory)

    r = await client.post("/devices/connect", headers=_auth(1), json={"nickname": "내 목걸이"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == THE_DEVICE_ID
    assert body["is_active_user"] is True
    assert body["nickname"] == "내 목걸이"

    # 다른 계정의 뷰: 현재 사용자가 아니고, 이름도 자기 것(미설정 → 기본 표시명)으로 보인다
    r = await client.get("/devices", headers=_auth(2))
    assert r.json()[0]["is_active_user"] is False
    assert r.json()[0]["nickname"] == DEFAULT_DEVICE_NICKNAME


@pytest.mark.asyncio
async def test_takeover_overwrites_active_user_and_keeps_names(api_client, hardware_online):
    """다른 계정이 쓰던 중이어도 connect 가 그대로 덮어쓴다(합의된 정책).
    body 없는 호출(설정의 [이 계정으로 전환])은 이름을 건드리지 않는다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    await client.post("/devices/connect", headers=_auth(1), json={"nickname": "첫째 목걸이"})

    r = await client.post("/devices/connect", headers=_auth(2))

    assert r.status_code == 200, r.text
    assert r.json()["is_active_user"] is True
    assert r.json()["nickname"] == DEFAULT_DEVICE_NICKNAME  # user2 는 이름을 지은 적 없음

    r = await client.get("/devices", headers=_auth(1))
    assert r.json()[0]["is_active_user"] is False  # 주도권을 잃었지만
    assert r.json()[0]["nickname"] == "첫째 목걸이"  # 내가 지은 이름은 그대로


@pytest.mark.asyncio
async def test_patch_renames_only_my_account(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)

    r = await client.patch(f"/devices/{THE_DEVICE_ID}", headers=_auth(1), json={"nickname": "바꾼 이름"})

    assert r.status_code == 200, r.text
    assert r.json()["nickname"] == "바꾼 이름"
    r = await client.get("/devices", headers=_auth(2))
    assert r.json()[0]["nickname"] == DEFAULT_DEVICE_NICKNAME

    r = await client.patch("/devices/999", headers=_auth(1), json={"nickname": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_releases_active_only_when_mine(api_client, hardware_online):
    """DELETE = 내 계정에서 연결 해제. 남의 주도권은 건드리지 못하고, 내 것이면 포인터만 비운다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    await client.post("/devices/connect", headers=_auth(1), json={"nickname": "내 목걸이"})

    r = await client.delete(f"/devices/{THE_DEVICE_ID}", headers=_auth(2))
    assert r.status_code == 200, r.text
    r = await client.get("/devices", headers=_auth(1))
    assert r.json()[0]["is_active_user"] is True  # user2 의 해제는 user1 에 영향 없음

    r = await client.delete(f"/devices/{THE_DEVICE_ID}", headers=_auth(1))
    assert r.status_code == 200, r.text
    r = await client.get("/devices", headers=_auth(1))
    assert r.json()[0]["is_active_user"] is False
    assert r.json()[0]["nickname"] == "내 목걸이"  # 이름은 해제 후에도 유지 — 재연결 시 그대로
