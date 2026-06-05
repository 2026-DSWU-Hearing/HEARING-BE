from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.sound import (
    CategoryItem,
    CategoryListResponse,
    SoundItem,
    SoundListResponse,
    SoundResponse,
)
from app.services import sound_service

router = APIRouter()


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories(_: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    categories = await sound_service.list_categories(db)
    return CategoryListResponse(
        categories=[CategoryItem(category_id=c.id, name=c.name) for c in categories]
    )


@router.get("", response_model=SoundListResponse)
async def list_sounds(
    category_id: int | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    sounds = await sound_service.list_sounds(db, category_id, keyword, page, size)
    return SoundListResponse(
        sounds=[
            SoundItem(
                sound_id=s.id,
                name=s.name,
                category_id=s.category_id,
                category_name=s.category.name,
            )
            for s in sounds
        ]
    )


@router.get("/{sound_id}", response_model=SoundResponse)
async def get_sound(sound_id: int, _: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await sound_service.get_sound(db, sound_id)
