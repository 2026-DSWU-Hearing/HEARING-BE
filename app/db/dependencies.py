from typing import AsyncGenerator

from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthException
from app.core.security import decode_token
from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_current_user_id(authorization: str | None = Header(default=None)) -> int:
    # MVP 개발용: 인증 우회 시 토큰 없이 dev 유저로 통과
    if settings.DEV_AUTH_BYPASS and not authorization:
        return settings.DEV_USER_ID
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthException("Missing bearer token")
    payload = decode_token(authorization.removeprefix("Bearer ").strip())
    if payload.get("type") != "access":
        raise AuthException("Invalid token type")
    return int(payload["sub"])


async def get_current_source(authorization: str | None = Header(default=None)) -> dict:
    """device_service에서 사용. source = 'device' | 'ai-server' | 'user'"""
    # MVP 개발용: 인증 우회 시 토큰 없이 dev 유저(source=user)로 통과
    if settings.DEV_AUTH_BYPASS and not authorization:
        return {"user_id": settings.DEV_USER_ID, "source": "user"}
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthException("Missing bearer token")
    payload = decode_token(authorization.removeprefix("Bearer ").strip())
    return {"user_id": int(payload["sub"]), "source": payload.get("source", "user")}
