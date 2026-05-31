from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, ValidationException
from app.db.functions import get_or_404
from app.models.mode import Mode, ModeSound
from app.schemas.mode import ModeCreate, ModeSoundsUpdate, ModeUpdate

MAX_MODES_PER_USER = 6
MIN_SOUNDS_PER_MODE = 1


async def list_modes(db: AsyncSession, user_id: int) -> list[Mode]:
    result = await db.execute(select(Mode).where(Mode.user_id == user_id).order_by(Mode.created_at))
    return list(result.scalars().all())


async def get_active_mode(db: AsyncSession, user_id: int) -> Mode | None:
    result = await db.execute(select(Mode).where(Mode.user_id == user_id, Mode.is_active.is_(True)))
    return result.scalar_one_or_none()


async def create_mode(db: AsyncSession, user_id: int, payload: ModeCreate) -> Mode:
    existing = await db.execute(select(Mode.id).where(Mode.user_id == user_id))
    if len(list(existing.scalars().all())) >= MAX_MODES_PER_USER:
        raise ValidationException(f"Maximum {MAX_MODES_PER_USER} modes allowed")
    if len(payload.sound_ids) < MIN_SOUNDS_PER_MODE:
        raise ValidationException(f"At least {MIN_SOUNDS_PER_MODE} sound required")

    mode = Mode(user_id=user_id, name=payload.name, icon=payload.icon, is_active=False)
    for sid in payload.sound_ids:
        mode.sound_links.append(ModeSound(sound_id=sid))
    db.add(mode)
    await db.commit()
    return await get_or_404(db, Mode, mode.id)


async def update_mode(db: AsyncSession, user_id: int, mode_id: int, payload: ModeUpdate) -> Mode:
    mode = await _get_owned_mode(db, user_id, mode_id)
    if payload.name is not None:
        mode.name = payload.name
    if payload.icon is not None:
        mode.icon = payload.icon
    await db.commit()
    return await get_or_404(db, Mode, mode.id)


async def delete_mode(db: AsyncSession, user_id: int, mode_id: int) -> None:
    mode = await _get_owned_mode(db, user_id, mode_id)
    await db.delete(mode)
    await db.commit()


async def activate_mode(db: AsyncSession, user_id: int, mode_id: int) -> Mode:
    mode = await _get_owned_mode(db, user_id, mode_id)
    await db.execute(
        update(Mode).where(Mode.user_id == user_id, Mode.id != mode_id).values(is_active=False)
    )
    mode.is_active = True
    await db.commit()
    return await get_or_404(db, Mode, mode.id)


async def update_mode_sounds(db: AsyncSession, user_id: int, mode_id: int, payload: ModeSoundsUpdate) -> Mode:
    if len(payload.sound_ids) < MIN_SOUNDS_PER_MODE:
        raise ValidationException(f"At least {MIN_SOUNDS_PER_MODE} sound required")
    mode = await _get_owned_mode(db, user_id, mode_id)
    mode.sound_links.clear()
    for sid in payload.sound_ids:
        mode.sound_links.append(ModeSound(sound_id=sid))
    await db.commit()
    return await get_or_404(db, Mode, mode.id)


async def _get_owned_mode(db: AsyncSession, user_id: int, mode_id: int) -> Mode:
    mode = await get_or_404(db, Mode, mode_id)
    if mode.user_id != user_id:
        raise ForbiddenException("Not your mode")
    return mode
