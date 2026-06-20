from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.schemas.auth import GoogleLoginRequest, RefreshRequest, TokenResponse
from app.services import auth_service

router = APIRouter()


# 로그인은 Google(GIS) + 게스트(데모) 두 가지만 지원.
# 이메일/비번 register·login·forgot·reset 은 제거됨.
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
