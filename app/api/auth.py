from fastapi import APIRouter, Depends
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.schemas.auth import (
    EmailAvailabilityResponse,
    GoogleLoginRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services import auth_service

router = APIRouter()


# 로그인: 이메일/비번(register·login) + Google(GIS) + 게스트(데모).
# forgot/reset(비번 재설정)은 후순위 — 미구현(현재 화면에도 없음).
@router.post("/register", response_model=UserResponse)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.register(db, payload)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.login(db, payload)


@router.get("/email-available", response_model=EmailAvailabilityResponse)
async def email_available(email: EmailStr, db: AsyncSession = Depends(get_db)):
    """회원가입 이메일 단계 중복확인: available=false 면 이미 가입된 이메일."""
    return EmailAvailabilityResponse(available=await auth_service.is_email_available(db, email))


@router.post("/google", response_model=TokenResponse)
async def google_login(payload: GoogleLoginRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.google_login(db, payload)


@router.post("/demo", response_model=TokenResponse)
async def demo_login(db: AsyncSession = Depends(get_db)):
    """게스트(데모) 로그인 — 포트폴리오 방문자가 계정 없이 둘러보기. 매번 새 샌드박스 유저."""
    return await auth_service.demo_login(db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    return await auth_service.refresh_tokens(payload.refresh_token)


@router.post("/logout")
async def logout():
    return {"ok": True}
