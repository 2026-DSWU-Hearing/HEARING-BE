import pytest
from jose import jwt

from app.core.config import settings
from app.core.exceptions import AuthException
from app.core.security import create_access_token, create_refresh_token
from app.db.dependencies import get_current_source, get_current_user_id


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_user_dependency_accepts_user_access_token():
    token = create_access_token(7, source="user")

    assert await get_current_user_id(f"Bearer {token}") == 7


@pytest.mark.asyncio
async def test_user_dependency_rejects_device_source():
    token = create_access_token(7, source="device")

    with pytest.raises(AuthException, match="Invalid token source"):
        await get_current_user_id(f"Bearer {token}")


@pytest.mark.asyncio
async def test_detection_dependency_accepts_ai_server_access_token():
    token = create_access_token(7, source="ai-server")

    claims = await get_current_source(f"Bearer {token}")

    assert claims.user_id == 7
    assert claims.source == "ai-server"


@pytest.mark.asyncio
async def test_detection_dependency_rejects_refresh_token():
    token = create_refresh_token(7)

    with pytest.raises(AuthException, match="Invalid token type"):
        await get_current_source(f"Bearer {token}")


@pytest.mark.asyncio
async def test_dependency_rejects_invalid_subject():
    token = _encode({"sub": "not-an-int", "source": "user", "type": "access"})

    with pytest.raises(AuthException, match="Invalid token subject"):
        await get_current_user_id(f"Bearer {token}")
