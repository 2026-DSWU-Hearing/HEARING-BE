from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.mode import ModeCreate, ModeResponse, ModeSoundsUpdate, ModeUpdate
from app.services import mode_service

router = APIRouter()


@router.get("", response_model=list[ModeResponse])
async def list_modes(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await mode_service.list_modes(db, user_id)


@router.post("", response_model=ModeResponse)
async def create_mode(payload: ModeCreate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await mode_service.create_mode(db, user_id, payload)


@router.patch("/{mode_id}", response_model=ModeResponse)
async def update_mode(mode_id: int, payload: ModeUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await mode_service.update_mode(db, user_id, mode_id, payload)


@router.delete("/{mode_id}")
async def delete_mode(mode_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await mode_service.delete_mode(db, user_id, mode_id)
    return {"ok": True}


@router.post("/{mode_id}/activate", response_model=ModeResponse)
async def activate_mode(mode_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await mode_service.activate_mode(db, user_id, mode_id)


@router.put("/{mode_id}/sounds", response_model=ModeResponse)
async def update_mode_sounds(mode_id: int, payload: ModeSoundsUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await mode_service.update_mode_sounds(db, user_id, mode_id, payload)
