from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.db.functions import get_or_404
from app.models.mode import Mode, ModeSound
from app.schemas.mode import ModeCreate, ModeSoundsUpdate

MAX_MODES_PER_USER = 6
MIN_SOUNDS_PER_MODE = 1


async def list_modes(db: AsyncSession, user_id: int) -> list[Mode]:
    result = await db.execute(select(Mode).where(Mode.user_id == user_id).order_by(Mode.created_at))
    return list(result.scalars().all())


async def get_mode(db: AsyncSession, user_id: int, mode_id: int) -> Mode:
    """소유한 모드 단건 조회(상세). sound_links/sound/category는 eager 로드됨."""
    return await _get_owned_mode(db, user_id, mode_id)


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


async def update_mode(
    db: AsyncSession, user_id: int, mode_id: int, name: str, icon: str, sound_ids: list[int]
) -> Mode:
    """프론트 PUT 계약: 이름/아이콘/소리 목록을 통째로 교체한다(부분 수정 아님)."""
    if len(sound_ids) < MIN_SOUNDS_PER_MODE:
        raise ValidationException(f"At least {MIN_SOUNDS_PER_MODE} sound required")
    mode = await _get_owned_mode(db, user_id, mode_id)
    mode.name = name
    mode.icon = icon
    mode.sound_links.clear()
    await db.flush()  # 기존 링크 DELETE를 먼저 반영 → 동일 sound_id 재추가 시 uq_mode_sound 충돌 방지
    for sid in sound_ids:
        mode.sound_links.append(ModeSound(sound_id=sid))
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
    await db.flush()  # 기존 링크 DELETE를 먼저 반영 → 동일 sound_id 재추가 시 uq_mode_sound 충돌 방지
    for sid in payload.sound_ids:
        mode.sound_links.append(ModeSound(sound_id=sid))
    await db.commit()
    return await get_or_404(db, Mode, mode.id)


async def remove_mode_sound(db: AsyncSession, user_id: int, mode_id: int, sound_id: int) -> None:
    """모드에서 소리 1건 제거. 마지막 1건은 남겨야 하므로 거부(모드당 최소 1개)."""
    mode = await _get_owned_mode(db, user_id, mode_id)
    link = next((ms for ms in mode.sound_links if ms.sound_id == sound_id), None)
    if link is None:
        raise NotFoundException("Sound not in this mode")
    if len(mode.sound_links) <= MIN_SOUNDS_PER_MODE:
        raise ValidationException(f"At least {MIN_SOUNDS_PER_MODE} sound required")
    mode.sound_links.remove(link)
    await db.commit()


async def set_mode_sound_active(
    db: AsyncSession, user_id: int, mode_id: int, sound_id: int, is_active: bool
) -> None:
    """모드 안의 소리 1건 on/off 토글(off=감지/알림 제외). 모드에 없는 소리면 404."""
    mode = await _get_owned_mode(db, user_id, mode_id)
    link = next((ms for ms in mode.sound_links if ms.sound_id == sound_id), None)
    if link is None:
        raise NotFoundException("Sound not in this mode")
    link.is_active = is_active
    await db.commit()


async def _get_owned_mode(db: AsyncSession, user_id: int, mode_id: int) -> Mode:
    mode = await get_or_404(db, Mode, mode_id)
    if mode.user_id != user_id:
        raise ForbiddenException("Not your mode")
    return mode
