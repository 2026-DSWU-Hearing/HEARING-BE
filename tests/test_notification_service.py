import json
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
        confidence=0.9,
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
        confidence=0.9,
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


@pytest.mark.asyncio
async def test_broadcast_payload_matches_list_item_schema(monkeypatch):
    """WS 페이로드와 GET /notifications 의 items 는 같은 모델에서 나와야 한다.

    FE 는 WS 이벤트를 목록 캐시 맨 앞에 그대로 끼워 넣으므로 두 경로가 갈라지면 같은 알림이
    두 번 보이거나 삭제 요청의 id 가 서버와 안 맞는다. 여기서 실제 직렬화 결과를 확인한다
    (다른 테스트들은 broadcast_detection 자체를 mock 해서 이 지점을 못 본다).
    """
    from app.schemas.notification import NotificationItem
    from app.websocket import manager as manager_module

    sent = []

    async def capture(user_id, payload):
        sent.append((user_id, payload))

    monkeypatch.setattr(manager_module.manager, "send_to_user", capture)

    notification = SimpleNamespace(
        id=7,
        sound_name="사이렌",
        sound_category="긴급",
        source="ai-server",
        confidence=0.95,
        location=None,
        detected_at=datetime(2026, 8, 22, 3, 4, 5, tzinfo=timezone.utc),
    )

    await detection_handler.broadcast_detection(42, notification)

    assert len(sent) == 1
    user_id, payload = sent[0]
    assert user_id == 42
    assert payload["type"] == "detection"

    data = payload["data"]
    assert set(data) == set(NotificationItem.model_fields)
    # 널이면 FE 가 이 이벤트가 섞인 페이지 전체를 무효로 본다.
    assert isinstance(data["confidence"], float)
    # 오프셋 없는 문자열은 브라우저가 UTC 로도 로컬로도 해석해 9시간 어긋난다.
    assert datetime.fromisoformat(data["detected_at"]).tzinfo is not None
    # WS 는 JSON 으로 나가므로 직렬화 가능한 값만 있어야 한다(datetime 객체가 남으면 터진다).
    json.dumps(payload)

