from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.functions import apply_pagination
from app.models.sound import Sound, SoundCategory


async def list_categories(db: AsyncSession) -> list[SoundCategory]:
    result = await db.execute(select(SoundCategory).order_by(SoundCategory.id))
    return list(result.scalars().all())


async def list_sounds(
    db: AsyncSession,
    category_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 50,
) -> list[Sound]:
    q = select(Sound)
    if category_id:
        q = q.where(Sound.category_id == category_id)
    if keyword:
        q = q.where(Sound.name.ilike(f"%{keyword}%"))
    q = apply_pagination(q.order_by(Sound.id), page, size)
    result = await db.execute(q)
    return list(result.scalars().all())
