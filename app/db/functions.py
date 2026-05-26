from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.db.base import Base

T = TypeVar("T", bound=Base)


async def get_or_404(db: AsyncSession, model: type[T], obj_id: int) -> T:
    result = await db.execute(select(model).where(model.id == obj_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise NotFoundException(f"{model.__name__} not found")
    return obj


def apply_pagination(query, page: int = 1, size: int = 20):
    return query.offset((page - 1) * size).limit(size)
