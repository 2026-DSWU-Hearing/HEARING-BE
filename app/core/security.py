import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import AuthException
from app.core.logger import logger

USER_ACCESS_SOURCES = frozenset({"user"})
DETECTION_ACCESS_SOURCES = frozenset({"device", "ai-server"})
DEVICE_WS_SOURCES = frozenset({"device"})


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    source: str


def _create_token(payload: dict[str, Any], expires_delta: timedelta) -> str:
    to_encode = payload.copy()
    to_encode.update({"exp": datetime.now(timezone.utc) + expires_delta})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int, source: str = "user") -> str:
    """source: 'user' | 'device' | 'ai-server'"""
    return _create_token(
        {"sub": str(user_id), "source": source, "type": "access"},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_device_token(days: int = 365) -> str:
    """하드웨어(ESP32) WS용 장수명 토큰. '정품 기기' 증명용 — 어느 기기인지는 접속 시 MAC 으로
    정해지므로 sub 를 특정 유저/기기에 묶지 않는다(0). 발급: scripts/make_device_token.py"""
    return _create_token(
        {"sub": "0", "source": "device", "type": "access"},
        timedelta(days=days),
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        {"sub": str(user_id), "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise AuthException("Invalid or expired token") from e


def decode_access_token(
    token: str,
    allowed_sources: Collection[str],
) -> AccessTokenClaims:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise AuthException("Invalid token type")

    source = payload.get("source")
    if not isinstance(source, str) or source not in allowed_sources:
        raise AuthException("Invalid token source")

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as e:
        raise AuthException("Invalid token subject") from e

    return AccessTokenClaims(user_id=user_id, source=source)


async def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Google ID 토큰(GIS) 검증 → {email, sub, name, picture, ...}.

    GOOGLE_CLIENT_ID 가 설정돼 있으면 aud(클라이언트)까지 검증한다(미설정 시 서명·발급자·만료만).
    검증에 구글 공개키를 받아오는 블로킹 네트워크 호출이 있어 asyncio.to_thread 로 감싼다.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    def _verify() -> dict[str, Any]:
        return google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID or None,
            # 기본값 0 이면 서버 시계가 구글보다 몇 초만 빨라도 "Token used too early" 로
            # 거절된다(로컬 개발의 최다 원인). 구글 권장대로 약간의 허용 오차를 둔다.
            clock_skew_in_seconds=10,
        )

    try:
        info = await asyncio.to_thread(_verify)
    except ValueError as e:  # 서명·aud·iss·만료 불일치
        # 원인별로(만료/시계오차/aud/서명) 메시지가 달라 진단에 필수인데, 삼키면 추적 불가.
        # 토큰 원문은 남기지 않고 실패 사유(str(e))만 기록한다.
        logger.warning("Google ID token verification failed: %s", e)
        raise AuthException("Invalid Google ID token") from e

    if not info.get("email"):
        raise AuthException("Google account has no email")
    return info
