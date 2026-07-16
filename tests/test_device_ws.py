from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.device import DetectionCreate
from app.services import notification_service
from app.websocket import detection_handler, device_handler
from app.websocket.manager import DeviceConnectionManager


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
    assert await manager.send_to_device(1, {"type": "vibrate"}) is False


@pytest.mark.asyncio
async def test_reconnect_replaces_old_connection():
    manager = DeviceConnectionManager()
    old, new = FakeWebSocket(), FakeWebSocket()
    await manager.connect(1, old)
    await manager.connect(1, new)

    assert old.closed_code == 4409
    # 교체된 옛 연결의 disconnect 는 활성 연결을 건드리지 않는다 (is_connected False 덮어쓰기 방지)
    assert manager.disconnect(1, old) is False
    assert await manager.send_to_device(1, {"type": "vibrate"}) is True
    assert new.sent == [{"type": "vibrate"}]


@pytest.mark.asyncio
async def test_close_device_force_disconnects():
    manager = DeviceConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(1, ws)

    assert await manager.close_device(1) is True
    assert ws.closed_code == 1000
    assert manager.disconnect(1, ws) is False  # 이미 빠져 있음
    assert await manager.close_device(1) is False  # 연결 없음


@pytest.mark.asyncio
async def test_send_vibrate_payload_and_offline_drop(monkeypatch):
    manager = DeviceConnectionManager()
    monkeypatch.setattr(device_handler, "device_manager", manager)

    # 오프라인 → 드롭
    assert await device_handler.send_vibrate(1, 70, "사이렌", "긴급", "LEFT") is False

    ws = FakeWebSocket()
    await manager.connect(1, ws)
    assert await device_handler.send_vibrate(1, 70, "사이렌", "긴급", "LEFT") is True
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
    device = SimpleNamespace(id=5)
    payload = DetectionCreate(
        sound_id=20,
        sound_name="사이렌",
        sound_category="긴급",
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
            "device_id": 5,
            "strength": 70,
            "sound_name": "사이렌",
            "sound_category": "긴급",
            "direction": "FRONT",
        }
    ]
