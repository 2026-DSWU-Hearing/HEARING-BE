from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.user import (
    AgreementUpdate,
    DoNotDisturbUpdate,
    FcmTokenUpdate,
    HapticUpdate,
    UserResponse,
    UserUpdate,
)
from app.services import user_service

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await user_service.get_me(db, user_id)


@router.patch("/me", response_model=UserResponse)
async def update_me(payload: UserUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await user_service.update_profile(db, user_id, payload)


@router.patch("/me/haptic", response_model=UserResponse)
async def update_haptic(payload: HapticUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await user_service.update_haptic(db, user_id, payload)


@router.patch("/me/do-not-disturb", response_model=UserResponse)
async def update_dnd(payload: DoNotDisturbUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await user_service.update_do_not_disturb(db, user_id, payload)


@router.post("/me/fcm-token", response_model=UserResponse)
async def update_fcm_token(payload: FcmTokenUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await user_service.update_fcm_token(db, user_id, payload)


@router.patch("/me/agreement", response_model=UserResponse)
async def update_agreement(payload: AgreementUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await user_service.update_agreement(db, user_id, payload)
