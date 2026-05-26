from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.sound import SoundCategoryResponse, SoundResponse
from app.services import sound_service

router = APIRouter()


@router.get("/categories", response_model=list[SoundCategoryResponse])
async def list_categories(_: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await sound_service.list_categories(db)


@router.get("", response_model=list[SoundResponse])
async def list_sounds(
    category_id: int | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await sound_service.list_sounds(db, category_id, keyword, page, size)


@router.get("/{sound_id}", response_model=SoundResponse)
async def get_sound(sound_id: int, _: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await sound_service.get_sound(db, sound_id)
