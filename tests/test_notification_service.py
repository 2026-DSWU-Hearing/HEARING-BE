from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.device import DetectionCreate
from app.services import notification_service, push_service
from app.websocket import detection_handler


class FakeResult:
    rowcount = 1


class FakeDatabaseSession:
    def __init__(self):
        self.commit_count = 0
        self.executed_statements = []

    def add(self, instance):
        self.added_instance = instance

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, instance):
        instance.id = 1

    async def execute(self, statement):
        self.executed_statements.append(statement)
        return FakeResult()


@pytest.mark.asyncio
async def test_handle_detection_removes_only_failed_fcm_token(monkeypatch):
    database_session = FakeDatabaseSession()
    user = SimpleNamespace(
        id=1,
        do_not_disturb=False,
        push_enabled=True,
        fcm_token="expired-token",
        haptic_strength=50,
    )
    device = SimpleNamespace(id=1, mac_address="44:1B:F6:D4:47:F0")
    payload = DetectionCreate(
        sound_id=20,
        sound_name="test sound",
        sound_category="test category",
        detected_at=datetime.now(timezone.utc),
    )

    async def get_active_sound_ids(*args, **kwargs):
        return {20}

    async def get_user(*args, **kwargs):
        return user

    async def raise_unregistered(*args, **kwargs):
        raise push_service.UnregisteredFcmTokenError

    async def broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(
        notification_service,
        "_get_active_mode_sound_ids",
        get_active_sound_ids,
    )
    monkeypatch.setattr(notification_service, "get_or_404", get_user)
    monkeypatch.setattr(push_service, "send_detection_push", raise_unregistered)
    monkeypatch.setattr(detection_handler, "broadcast_detection", broadcast)

    await notification_service.handle_detection(
        db=database_session,
        user_id=1,
        device=device,
        payload=payload,
        source="ai-server",
    )

    assert database_session.commit_count == 2
    assert len(database_session.executed_statements) == 1
    statement = str(database_session.executed_statements[0])
    assert "users.id" in statement
    assert "users.fcm_token" in statement


@pytest.mark.asyncio
async def test_handle_detection_skips_only_fcm_when_push_disabled(monkeypatch):
    database_session = FakeDatabaseSession()
    user = SimpleNamespace(
        id=1,
        do_not_disturb=False,
        push_enabled=False,
        fcm_token="valid-token",
        haptic_strength=50,
    )
    device = SimpleNamespace(id=1, mac_address="44:1B:F6:D4:47:F0")
    payload = DetectionCreate(
        sound_id=20,
        sound_name="test sound",
        sound_category="test category",
        detected_at=datetime.now(timezone.utc),
    )
    broadcasts = []

    async def get_active_sound_ids(*args, **kwargs):
        return {20}

    async def get_user(*args, **kwargs):
        return user

    async def fail_push(*args, **kwargs):
        raise AssertionError("FCM push should not be sent when push_enabled is false")

    async def broadcast(user_id, notification):
        broadcasts.append((user_id, notification))

    monkeypatch.setattr(
        notification_service,
        "_get_active_mode_sound_ids",
        get_active_sound_ids,
    )
    monkeypatch.setattr(notification_service, "get_or_404", get_user)
    monkeypatch.setattr(push_service, "send_detection_push", fail_push)
    monkeypatch.setattr(detection_handler, "broadcast_detection", broadcast)

    notification = await notification_service.handle_detection(
        db=database_session,
        user_id=1,
        device=device,
        payload=payload,
        source="ai-server",
    )

    assert notification is database_session.added_instance
    assert database_session.commit_count == 1
    assert database_session.executed_statements == []
    assert broadcasts == [(1, notification)]
