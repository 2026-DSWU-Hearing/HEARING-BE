"""기기 설정 전달(settings_update) — 넥밴드가 백엔드 없이도 판단하도록 설정을 기기에 알린다.

계약(하드웨어 feat/ondevice-ai 의 backend_ws.cpp 와 합의):
  {"type":"settings_update","emergency_alert_enabled":bool,"do_not_disturb":bool,"haptic_strength":0~100}
  - 세 값을 매번 모두 보낸다
  - 기기 접속 시 1회 + 설정이 바뀔 때마다
넥밴드는 공유 기기고 설정은 계정별이라, 보내는 값은 항상 현재 사용자(active user)의 것이다.
"""

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.security import create_access_token
from app.models.device import Device
from app.models.user import User
from app.services.device_service import THE_DEVICE_ID
from app.websocket import device_handler
from app.websocket.device_handler import DEFAULT_DEVICE_SETTINGS, build_settings_message
from app.websocket.manager import device_manager

MAC = settings.DEVICE_MAC_ADDRESS
ACTIVE, OTHER = 1, 2


class FakeHardware:
    """넥밴드 대역 — 서버가 보낸 메시지를 모은다."""

    def __init__(self):
        self.sent: list[dict] = []

    async def accept(self):
        pass

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000):
        pass

    def settings_updates(self) -> list[dict]:
        return [m for m in self.sent if m["type"] == "settings_update"]


@pytest_asyncio.fixture
async def hardware():
    ws = FakeHardware()
    await device_manager.connect(MAC, ws)
    yield ws
    device_manager.disconnect(MAC, ws)


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, source="user")}


async def _seed(session_factory, *, active_user_id: int | None = ACTIVE) -> None:
    async with session_factory() as db:
        db.add_all([
            User(id=ACTIVE, email="a@t.local", nickname="a", terms_agreed=True, haptic_strength=70),
            User(id=OTHER, email="o@t.local", nickname="o", terms_agreed=True, haptic_strength=20),
        ])
        await db.flush()
        db.add(Device(id=THE_DEVICE_ID, mac_address=MAC, active_user_id=active_user_id))
        await db.commit()


# --- "긴급 소리 알림 받기" 설정 -----------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_alert_defaults_to_on_and_can_be_toggled(api_client):
    """기본값은 넥밴드 펌웨어 기본값과 같은 true — 어긋나면 기기가 붙는 순간 동작이 바뀐다."""
    client, session_factory = api_client
    await _seed(session_factory)

    assert (await client.get("/users/me", headers=_auth(ACTIVE))).json()["emergency_alert_enabled"] is True

    r = await client.patch(
        "/users/me/emergency-alert", headers=_auth(ACTIVE), json={"emergency_alert_enabled": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["emergency_alert_enabled"] is False
    assert (await client.get("/users/me", headers=_auth(ACTIVE))).json()["emergency_alert_enabled"] is False


@pytest.mark.asyncio
async def test_emergency_alert_rejects_missing_field(api_client):
    client, session_factory = api_client
    await _seed(session_factory)

    r = await client.patch("/users/me/emergency-alert", headers=_auth(ACTIVE), json={})

    assert r.status_code == 422


# --- 설정 변경 시 전송 --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "body", "expected"),
    [
        ("/users/me/do-not-disturb", {"do_not_disturb": True},
         {"emergency_alert_enabled": True, "do_not_disturb": True, "haptic_strength": 70}),
        ("/users/me/emergency-alert", {"emergency_alert_enabled": False},
         {"emergency_alert_enabled": False, "do_not_disturb": False, "haptic_strength": 70}),
        ("/users/me/haptic", {"haptic_strength": 30},
         {"emergency_alert_enabled": True, "do_not_disturb": False, "haptic_strength": 30}),
    ],
)
async def test_each_setting_change_sends_all_three_values(api_client, hardware, path, body, expected):
    """하나만 바꿔도 세 값을 모두 보낸다 — 넥밴드는 빠진 필드를 현재값으로 두므로
    일부만 보내면 기기와 서버가 갈라져도 알 수 없다."""
    client, session_factory = api_client
    await _seed(session_factory)

    r = await client.patch(path, headers=_auth(ACTIVE), json=body)

    assert r.status_code == 200, r.text
    assert hardware.settings_updates() == [{"type": "settings_update", **expected}]


@pytest.mark.asyncio
async def test_setting_change_by_non_active_user_is_not_sent(api_client, hardware):
    """남이 쓰고 있는 넥밴드가 내 방해금지 때문에 조용해지면 안 된다."""
    client, session_factory = api_client
    await _seed(session_factory)

    r = await client.patch("/users/me/do-not-disturb", headers=_auth(OTHER), json={"do_not_disturb": True})

    assert r.status_code == 200, r.text
    assert hardware.settings_updates() == []


@pytest.mark.asyncio
async def test_setting_change_succeeds_when_hardware_is_offline(api_client):
    """넥밴드가 꺼져 있어도 앱 설정 저장은 성공해야 한다 — 다시 붙을 때 최신 값을 받는다."""
    client, session_factory = api_client
    await _seed(session_factory)

    r = await client.patch("/users/me/do-not-disturb", headers=_auth(ACTIVE), json={"do_not_disturb": True})

    assert r.status_code == 200 and r.json()["do_not_disturb"] is True


# --- 현재 사용자 전환 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_switching_active_user_sends_new_users_settings(api_client, hardware):
    """설정은 계정별이다 — 사용자가 바뀌면 넥밴드의 세기·방해금지도 새 사용자 것이어야 한다."""
    client, session_factory = api_client
    await _seed(session_factory)

    r = await client.post("/devices/connect", headers=_auth(OTHER))

    assert r.status_code == 200, r.text
    assert hardware.settings_updates() == [
        {"type": "settings_update", "emergency_alert_enabled": True, "do_not_disturb": False, "haptic_strength": 20}
    ]


@pytest.mark.asyncio
async def test_releasing_device_resets_settings_to_defaults(api_client, hardware):
    """떠난 사용자의 방해금지·세기가 넥밴드에 남아 다음 사람에게 적용되면 안 된다."""
    client, session_factory = api_client
    await _seed(session_factory)
    await client.patch("/users/me/do-not-disturb", headers=_auth(ACTIVE), json={"do_not_disturb": True})

    r = await client.delete(f"/devices/{THE_DEVICE_ID}", headers=_auth(ACTIVE))

    assert r.status_code == 200, r.text
    assert hardware.settings_updates()[-1] == {"type": "settings_update", **DEFAULT_DEVICE_SETTINGS}


# --- 기기 접속 시 1회 ---------------------------------------------------------------


class ConnectingHardware(FakeHardware):
    """접속 직후 서버가 보낸 것만 보고 바로 끊는 넥밴드."""

    async def receive_text(self):
        from fastapi import WebSocketDisconnect

        raise WebSocketDisconnect()


@pytest.fixture
def handler_db(monkeypatch, test_session_factory, db):
    # db 픽스처는 쓰지 않지만 의존한다 — 테스트 후 TRUNCATE 가 거기 달려 있어서, 빠지면
    # 여기서 넣은 행이 다음 테스트로 새어 나간다.
    monkeypatch.setattr(device_handler, "AsyncSessionLocal", test_session_factory)
    return test_session_factory


@pytest.mark.asyncio
async def test_device_receives_active_users_settings_on_connect(handler_db):
    """넥밴드는 설정을 저장하지 않는다(재부팅하면 기본값) — 붙자마자 현재 값을 알려준다."""
    await _seed(handler_db)
    async with handler_db() as db:
        user = await db.get(User, ACTIVE)
        user.do_not_disturb = True
        await db.commit()
    ws = ConnectingHardware()

    await device_handler.handle_device_socket(ws, MAC)

    assert ws.settings_updates() == [
        {"type": "settings_update", "emergency_alert_enabled": True, "do_not_disturb": True, "haptic_strength": 70}
    ]


@pytest.mark.asyncio
async def test_device_receives_defaults_on_connect_without_active_user(handler_db):
    await _seed(handler_db, active_user_id=None)
    ws = ConnectingHardware()

    await device_handler.handle_device_socket(ws, MAC)

    assert ws.settings_updates() == [{"type": "settings_update", **DEFAULT_DEVICE_SETTINGS}]


# --- 메시지 형태 -------------------------------------------------------------------


def test_default_settings_match_firmware_defaults():
    """펌웨어 settings.cpp 의 기본값(긴급 알림 켜짐, 방해금지 꺼짐, 세기 50)과 같아야 한다."""
    assert build_settings_message(None) == {
        "type": "settings_update",
        "emergency_alert_enabled": True,
        "do_not_disturb": False,
        "haptic_strength": 50,
    }
