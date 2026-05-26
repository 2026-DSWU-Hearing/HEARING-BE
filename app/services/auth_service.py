from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthException, ConflictException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_google_id_token,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import GoogleLoginRequest, LoginRequest, RegisterRequest, TokenResponse


async def register(db: AsyncSession, payload: RegisterRequest) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise ConflictException("Email already registered")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname,
        disability_type=payload.disability_type,
        terms_agreed=payload.terms_agreed,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login(db: AsyncSession, payload: LoginRequest) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise AuthException("Invalid credentials")
    return _issue_tokens(user.id)


async def google_login(db: AsyncSession, payload: GoogleLoginRequest) -> TokenResponse:
    info = await verify_google_id_token(payload.id_token)
    result = await db.execute(select(User).where(User.google_sub == info["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            email=info["email"],
            nickname=info.get("name", info["email"].split("@")[0]),
            is_google_user=True,
            google_sub=info["sub"],
            terms_agreed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return _issue_tokens(user.id)


async def refresh_tokens(refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthException("Invalid refresh token")
    return _issue_tokens(int(payload["sub"]))


def _issue_tokens(user_id: int) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id, source="user"),
        refresh_token=create_refresh_token(user_id),
    )


async def forgot_password(db: AsyncSession, email: str) -> None:
    raise NotImplementedError


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    raise NotImplementedError
