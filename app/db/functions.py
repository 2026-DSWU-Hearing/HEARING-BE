from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.db.base import Base

T = TypeVar("T", bound=Base)


async def get_or_404(db: AsyncSession, model: type[T], obj_id: int) -> T:
    result = await db.execute(select(model).where(model.id == obj_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise NotFoundException(f"{model.__name__} not found")
    return obj


async def get_owned_or_403(db: AsyncSession, model: type[T], obj_id: int, user_id: int) -> T:
    """get_or_404 + 소유권 검사. 소유자(user_id) 불일치 시 403."""
    obj = await get_or_404(db, model, obj_id)
    if obj.user_id != user_id:
        raise ForbiddenException(f"Not your {model.__name__.lower()}")
    return obj


def apply_pagination(query, page: int = 1, size: int = 20):
    return query.offset((page - 1) * size).limit(size)
