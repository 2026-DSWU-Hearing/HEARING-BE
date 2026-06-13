from types import SimpleNamespace

import pytest
from firebase_admin import messaging

from app.services import push_service


@pytest.mark.asyncio
async def test_send_detection_push_raises_for_unregistered_token(monkeypatch):
    notification = SimpleNamespace(
        id=1,
        sound_name="test sound",
        risk_level="HIGH",
        sound_category="test category",
        source="ai-server",
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
        risk_level="HIGH",
        sound_category="test category",
        source="ai-server",
    )

    monkeypatch.setattr(push_service, "_ensure_initialized", lambda: None)

    async def raise_transport_error(*args, **kwargs):
        raise RuntimeError("temporary network failure")

    monkeypatch.setattr(push_service.asyncio, "to_thread", raise_transport_error)

    await push_service.send_detection_push("valid-token", notification)
