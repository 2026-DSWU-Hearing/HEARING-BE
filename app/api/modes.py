from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mode_icons import MODE_ICONS
from app.db.dependencies import get_current_user_id, get_db
from app.models.mode import Mode
from app.schemas.mode import (
    ModeActivateResponse,
    ModeCreate,
    ModeCreateRequest,
    ModeDetailResponse,
    ModeDetailSoundItem,
    ModeIconItem,
    ModeIconListResponse,
    ModeListItem,
    ModeListResponse,
    ModeSoundActiveResponse,
    ModeSoundActiveUpdate,
    ModeSoundItem,
    ModeSoundsResponse,
    ModeSoundsUpdate,
    ModeSoundsUpdateRequest,
    ModeUpdateRequest,
    ModeWriteResponse,
)
from app.services import mode_service

router = APIRouter()


def _write_response(mode: Mode) -> ModeWriteResponse:
    return ModeWriteResponse(
        mode_id=mode.id,
        name=mode.name,
        icon=mode.icon,
        sounds=[ModeSoundItem(sound_id=s.id, name=s.name) for s in mode.sounds],
    )


@router.get("", response_model=ModeListResponse)
async def list_modes(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    modes = await mode_service.list_modes(db, user_id)
    return ModeListResponse(
        modes=[
            ModeListItem(mode_id=m.id, name=m.name, icon=m.icon, is_active=m.is_active)
            for m in modes
        ]
    )


@router.get("/icons", response_model=ModeIconListResponse)
async def list_mode_icons(_: int = Depends(get_current_user_id)):
    return ModeIconListResponse(
        icons=[
            ModeIconItem(
                mode_id=i.mode_id,
                name_ko=i.name_ko,
                name_key=i.name_key,
                icon_key=i.icon_key,
            )
            for i in MODE_ICONS
        ]
    )


@router.get("/{mode_id}", response_model=ModeDetailResponse)
async def get_mode(mode_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    mode = await mode_service.get_mode(db, user_id, mode_id)
    return ModeDetailResponse(
        mode_id=mode.id,
        name=mode.name,
        icon=mode.icon,
        is_active=mode.is_active,
        sounds=[
            ModeDetailSoundItem(
                sound_id=link.sound.id,
                name=link.sound.name,
                category=link.sound.category.name,
                is_active=link.is_active,
            )
            for link in mode.sound_links
        ],
    )


@router.post("", response_model=ModeWriteResponse)
async def create_mode(payload: ModeCreateRequest, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    mode = await mode_service.create_mode(
        db,
        user_id,
        ModeCreate(name=payload.name, icon=payload.icon, sound_ids=[s.sound_id for s in payload.sounds]),
    )
    return _write_response(mode)


@router.put("/{mode_id}", response_model=ModeWriteResponse)
async def update_mode(mode_id: int, payload: ModeUpdateRequest, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    mode = await mode_service.update_mode(
        db,
        user_id,
        mode_id,
        name=payload.name,
        icon=payload.icon,
        sound_ids=[s.sound_id for s in payload.sounds],
    )
    return _write_response(mode)


@router.delete("/{mode_id}")
async def delete_mode(mode_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await mode_service.delete_mode(db, user_id, mode_id)
    return {"ok": True}


@router.patch("/{mode_id}/activate", response_model=ModeActivateResponse)
async def activate_mode(mode_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    mode = await mode_service.activate_mode(db, user_id, mode_id)
    return ModeActivateResponse(mode_id=mode.id, is_active=mode.is_active)


@router.put("/{mode_id}/sounds", response_model=ModeSoundsResponse)
async def update_mode_sounds(mode_id: int, payload: ModeSoundsUpdateRequest, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    mode = await mode_service.update_mode_sounds(
        db,
        user_id,
        mode_id,
        ModeSoundsUpdate(sound_ids=[s.sound_id for s in payload.sounds]),
    )
    return ModeSoundsResponse(
        mode_id=mode.id,
        sounds=[ModeSoundItem(sound_id=s.id, name=s.name) for s in mode.sounds],
    )


@router.delete("/{mode_id}/sounds/{sound_id}")
async def remove_mode_sound(mode_id: int, sound_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await mode_service.remove_mode_sound(db, user_id, mode_id, sound_id)
    return {"ok": True}


@router.patch("/{mode_id}/sounds/{sound_id}", response_model=ModeSoundActiveResponse)
async def update_mode_sound_active(
    mode_id: int,
    sound_id: int,
    payload: ModeSoundActiveUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """모드 안의 소리 1건 on/off 토글. body: {"is_active": bool} (off=감지/알림 제외)"""
    await mode_service.set_mode_sound_active(db, user_id, mode_id, sound_id, payload.is_active)
    return ModeSoundActiveResponse(mode_id=mode_id, sound_id=sound_id, is_active=payload.is_active)
