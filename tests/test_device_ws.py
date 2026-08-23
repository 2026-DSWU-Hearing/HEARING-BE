from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.device import Device
from app.models.user import User
from app.schemas.device import DetectionCreate
from app.services import notification_service
from app.websocket import detection_handler, device_handler
from app.websocket.manager import DeviceConnectionManager

MAC = "44:1B:F6:D4:47:F0"


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent: list[dict] = []
        self.closed_code: int | None = None

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000):
        self.closed_code = code


class FakeDatabaseSession:
    def __init__(self):
        self.commit_count = 0

    def add(self, instance):
        self.added_instance = instance

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, instance):
        instance.id = 1


@pytest.mark.asyncio
async def test_send_to_device_returns_false_when_offline():
    manager = DeviceConnectionManager()
    assert await manager.send_to_device(MAC, {"type": "vibrate"}) is False


@pytest.mark.asyncio
async def test_reconnect_replaces_old_connection():
    manager = DeviceConnectionManager()
    old, new = FakeWebSocket(), FakeWebSocket()
    await manager.connect(MAC, old)
    await manager.connect(MAC, new)

    assert old.closed_code == 4409
    # 교체된 옛 연결의 disconnect 는 활성 연결을 건드리지 않는다 (is_connected False 덮어쓰기 방지)
    assert manager.disconnect(MAC, old) is False
    assert await manager.send_to_device(MAC, {"type": "vibrate"}) is True
    assert new.sent == [{"type": "vibrate"}]


@pytest.mark.asyncio
async def test_is_connected_reflects_live_registry():
    """[기기 연결] 버튼의 즉시 확인이 보는 값 — 접속/해제가 바로 반영돼야 한다."""
    manager = DeviceConnectionManager()
    ws = FakeWebSocket()
    assert manager.is_connected(MAC) is False

    await manager.connect(MAC, ws)
    assert manager.is_connected(MAC) is True

    manager.disconnect(MAC, ws)
    assert manager.is_connected(MAC) is False


@pytest.mark.asyncio
async def test_send_vibrate_payload_and_offline_drop(monkeypatch):
    manager = DeviceConnectionManager()
    monkeypatch.setattr(device_handler, "device_manager", manager)

    # 오프라인 → 드롭
    assert await device_handler.send_vibrate(MAC, 70, "사이렌", "긴급", "LEFT") is False

    ws = FakeWebSocket()
    await manager.connect(MAC, ws)
    assert await device_handler.send_vibrate(MAC, 70, "사이렌", "긴급", "LEFT") is True
    assert ws.sent == [
        {
            "type": "vibrate",
            "strength": 70,
            "sound_name": "사이렌",
            "sound_category": "긴급",
            "direction": "LEFT",
        }
    ]


@pytest.mark.asyncio
async def test_handle_detection_sends_vibrate_with_user_strength(monkeypatch):
    database_session = FakeDatabaseSession()
    user = SimpleNamespace(
        id=1,
        do_not_disturb=False,
        push_enabled=False,
        fcm_token=None,
        haptic_strength=70,
    )
    device = SimpleNamespace(id=5, mac_address=MAC)
    payload = DetectionCreate(
        sound_id=20,
        sound_name="사이렌",
        sound_category="긴급",
        confidence=0.9,
        detected_at=datetime.now(timezone.utc),
        direction="FRONT",
    )

    async def get_active_sound_ids(*args, **kwargs):
        return {20}

    async def get_user(*args, **kwargs):
        return user

    async def broadcast(*args, **kwargs):
        return None

    vibrate_calls = []

    async def fake_vibrate(**kwargs):
        vibrate_calls.append(kwargs)
        return True

    monkeypatch.setattr(notification_service, "_get_active_mode_sound_ids", get_active_sound_ids)
    monkeypatch.setattr(notification_service, "get_or_404", get_user)
    monkeypatch.setattr(detection_handler, "broadcast_detection", broadcast)
    monkeypatch.setattr(device_handler, "send_vibrate", fake_vibrate)

    await notification_service.handle_detection(
        db=database_session,
        user_id=1,
        device=device,
        payload=payload,
        source="ai-server",
    )

    assert vibrate_calls == [
        {
            "mac": MAC,
            "strength": 70,
            "sound_name": "사이렌",
            "sound_category": "긴급",
            "direction": "FRONT",
        }
    ]


# --- 물리 기기 1행: WS 수명주기 → 그 행의 상태 갱신 ---------------------------


async def _seed_physical_device(db) -> None:
    db.add(User(id=1, email="a@t.local", nickname="a", terms_agreed=True))
    await db.flush()
    db.add(Device(id=1, mac_address=MAC))
    await db.commit()


@pytest.mark.asyncio
async def test_ws_lifecycle_updates_physical_device_row(db, test_session_factory, monkeypatch):
    """하드웨어 WS 접속/해제가 물리 기기 행의 is_connected 를 갱신한다."""
    await _seed_physical_device(db)
    monkeypatch.setattr(device_handler, "AsyncSessionLocal", test_session_factory)

    # 소문자 MAC 접속도 정규화돼 우리 기기로 해석된다
    assert await device_handler.resolve_registered_mac(MAC.lower()) == MAC
    assert await device_handler.resolve_registered_mac("FF:FF:FF:FF:FF:FF") is None

    await device_handler._set_connected(MAC, True)
    rows = (await db.execute(select(Device.is_connected))).scalars().all()
    assert rows == [True]

    await device_handler._set_connected(MAC, False)
    rows = (await db.execute(select(Device))).scalars().all()
    assert [d.is_connected for d in rows] == [False]
    assert all(d.last_seen_at is not None for d in rows)


@pytest.mark.asyncio
async def test_startup_reset_clears_stale_connections(db, test_session_factory, monkeypatch):
    """서버 기동 시 리셋 — 크래시·과거 데이터로 남은 is_connected=true 를 끈다."""
    await _seed_physical_device(db)
    await db.execute(Device.__table__.update().values(is_connected=True))
    await db.commit()
    monkeypatch.setattr(device_handler, "AsyncSessionLocal", test_session_factory)

    await device_handler.reset_all_connections()

    rows = (await db.execute(select(Device.is_connected))).scalars().all()
    assert rows == [False]
