from types import SimpleNamespace

import pytest
from firebase_admin import messaging

from app.services import push_service


@pytest.mark.asyncio
async def test_send_detection_push_raises_for_unregistered_token(monkeypatch):
    notification = SimpleNamespace(
        id=1,
        sound_name="test sound",
        sound_category="test category",
        source="ai-server",
        direction="UNKNOWN",
        ondevice_vibrated=False,
    )

    monkeypatch.setattr(push_service, "_ensure_initialized", lambda: None)

    async def raise_unregistered(*args, **kwargs):
        raise messaging.UnregisteredError("Device unregistered")

    monkeypatch.setattr(push_service.asyncio, "to_thread", raise_unregistered)

    with pytest.raises(push_service.UnregisteredFcmTokenError):
        await push_service.send_detection_push("expired-token", notification)


@pytest.mark.asyncio
async def test_send_detection_push_swallows_other_fcm_errors(monkeypatch):
    notification = SimpleNamespace(
        id=1,
        sound_name="test sound",
        sound_category="test category",
        source="ai-server",
        direction="UNKNOWN",
        ondevice_vibrated=False,
    )

    monkeypatch.setattr(push_service, "_ensure_initialized", lambda: None)

    async def raise_transport_error(*args, **kwargs):
        raise RuntimeError("temporary network failure")

    monkeypatch.setattr(push_service.asyncio, "to_thread", raise_transport_error)

    await push_service.send_detection_push("valid-token", notification)


@pytest.mark.asyncio
async def test_send_detection_push_carries_direction_and_ondevice_as_string_keys(monkeypatch):
    """알림 문구는 FE 서비스워커가 그리므로 방향·온디바이스 여부는 body 에 섞지 않고 별도 키로.
    FCM data 값은 전부 문자열이어야 한다(bool 을 그대로 넣으면 SDK 가 거부)."""
    notification = SimpleNamespace(
        id=9,
        sound_name="사이렌",
        sound_category="긴급",
        source="ai-server",
        direction="LEFT",
        ondevice_vibrated=True,
    )
    monkeypatch.setattr(push_service, "_ensure_initialized", lambda: None)

    sent = []

    async def capture(fn, message):
        sent.append(message)

    monkeypatch.setattr(push_service.asyncio, "to_thread", capture)

    await push_service.send_detection_push("token", notification)

    data = sent[0].data
    assert data["direction"] == "LEFT"
    assert data["ondevice_vibrated"] == "true"
    assert data["sound_category"] == "긴급"
    assert all(isinstance(v, str) for v in data.values())
