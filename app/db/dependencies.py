from typing import AsyncGenerator

from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthException
from app.core.security import (
    AccessTokenClaims,
    DETECTION_ACCESS_SOURCES,
    USER_ACCESS_SOURCES,
    decode_access_token,
)
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
    token = _extract_bearer_token(authorization)
    return decode_access_token(token, USER_ACCESS_SOURCES).user_id


async def get_current_source(
    authorization: str | None = Header(default=None),
) -> AccessTokenClaims:
    """device_service에서 사용. source = 'device' | 'ai-server'"""
    # MVP 개발용: 인증 우회 시 AI 서버가 dev 유저의 감지를 보낸 것으로 처리
    if settings.DEV_AUTH_BYPASS and not authorization:
        return AccessTokenClaims(user_id=settings.DEV_USER_ID, source="ai-server")
    token = _extract_bearer_token(authorization)
    return decode_access_token(token, DETECTION_ACCESS_SOURCES)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthException("Missing bearer token")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthException("Missing bearer token")
    return token.strip()
