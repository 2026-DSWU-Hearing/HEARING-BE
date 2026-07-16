from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import check_guest_login_limit
from app.db.dependencies import get_db
from app.schemas.auth import GoogleLoginRequest, LogoutRequest, RefreshRequest, TokenResponse
from app.services import auth_service

router = APIRouter()


# 로그인: Google(GIS) + 게스트(데모) 전용. 이메일/비번 로그인은 미사용이라 제거.
@router.post("/google", response_model=TokenResponse)
async def google_login(payload: GoogleLoginRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.google_login(db, payload)


@router.post("/guest", response_model=TokenResponse)
async def guest_login(request: Request, db: AsyncSession = Depends(get_db)):
    """게스트(데모) 로그인 — 포트폴리오 방문자가 계정 없이 둘러보기. 매번 새 샌드박스 유저.
    호출마다 유저+샘플데이터가 생성되므로 IP당 시간당 횟수를 제한한다(Redis, 초과 시 429)."""
    await check_guest_login_limit(request.client.host if request.client else "unknown")
    return await auth_service.guest_login(db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    return await auth_service.refresh_tokens(payload.refresh_token)


@router.post("/logout")
async def logout(payload: LogoutRequest | None = None):
    """로그아웃. refresh_token 을 보내면 남은 수명 동안 블랙리스트에 올려 재발급을 차단한다.
    (body 없이 호출해도 성공 — 클라이언트 측 토큰 폐기만 하는 기존 동작 유지)"""
    if payload is not None and payload.refresh_token:
        await auth_service.logout(payload.refresh_token)
    return {"ok": True}
