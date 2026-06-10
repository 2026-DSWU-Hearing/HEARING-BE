from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sound import Sound, SoundCategory


async def list_categories(db: AsyncSession) -> list[SoundCategory]:
    result = await db.execute(select(SoundCategory).order_by(SoundCategory.id))
    return list(result.scalars().all())


async def list_sounds(
    db: AsyncSession,
    category_id: int | None = None,
    keyword: str | None = None,
) -> list[Sound]:
    q = select(Sound)
    if category_id:
        q = q.where(Sound.category_id == category_id)
    if keyword:
        q = q.where(Sound.name.ilike(f"%{keyword}%"))
    # 소리 카탈로그는 고정 분류라 작음 → 페이징 없이 전체 반환(FE 가 클라단에서 카테고리로 거름).
    q = q.order_by(Sound.id)
    result = await db.execute(q)
    return list(result.scalars().all())
