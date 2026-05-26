"""소리 필터링 진입 서비스. 웨어러블(source='device')과 HEARING-AI-SE(source='ai-server')의
감지 결과를 모두 POST /devices/{id}/detections로 받아 처리한다."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.core.logger import logger
from app.db.functions import get_or_404
from app.models.device import Device
from app.schemas.device import DetectionCreate, DeviceCreate, DeviceUpdate


async def list_devices(db: AsyncSession, user_id: int) -> list[Device]:
    result = await db.execute(select(Device).where(Device.user_id == user_id))
    return list(result.scalars().all())


async def create_device(db: AsyncSession, user_id: int, payload: DeviceCreate) -> Device:
    device = Device(user_id=user_id, nickname=payload.nickname, mac_address=payload.mac_address)
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


async def update_device(db: AsyncSession, user_id: int, device_id: int, payload: DeviceUpdate) -> Device:
    device = await _get_owned_device(db, user_id, device_id)
    if payload.nickname is not None:
        device.nickname = payload.nickname
    if payload.battery_level is not None:
        device.battery_level = payload.battery_level
    if payload.is_connected is not None:
        device.is_connected = payload.is_connected
    await db.commit()
    await db.refresh(device)
    return device


async def delete_device(db: AsyncSession, user_id: int, device_id: int) -> None:
    device = await _get_owned_device(db, user_id, device_id)
    await db.delete(device)
    await db.commit()


async def handle_detection(
    db: AsyncSession,
    device_id: int,
    payload: DetectionCreate,
    source: str,
) -> None:
    """소리 필터링 흐름 진입점.

    1) JWT source 확인 (caller가 이미 검증, 여기서는 값만 사용)
    2) Device 존재 확인 → user_id 파악
    3) notification_service에 위임 (활성 모드 필터 + 저장 + 푸시)
    """
    from app.services import notification_service

    device = await get_or_404(db, Device, device_id)
    logger.info(
        "detection received device_id=%s user_id=%s source=%s sound=%s",
        device_id, device.user_id, source, payload.sound_name,
    )
    await notification_service.handle_detection(
        db=db,
        user_id=device.user_id,
        device=device,
        payload=payload,
        source=source,
    )


async def _get_owned_device(db: AsyncSession, user_id: int, device_id: int) -> Device:
    device = await get_or_404(db, Device, device_id)
    if device.user_id != user_id:
        raise ForbiddenException("Not your device")
    return device
