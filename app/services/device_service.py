"""소리 필터링 진입 서비스. 웨어러블(source='device')과 HEARING-AI-SE(source='ai-server')의
감지 결과를 모두 POST /devices/{id}/detections로 받아 처리한다."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.core.logger import logger
from app.db.functions import get_or_404, get_owned_or_403
from app.models.device import Device
from app.schemas.device import DetectionCreate, DeviceCreate, DeviceUpdate


async def list_devices(db: AsyncSession, user_id: int) -> list[Device]:
    result = await db.execute(select(Device).where(Device.user_id == user_id))
    return list(result.scalars().all())


async def create_device(db: AsyncSession, user_id: int, payload: DeviceCreate) -> Device:
    # 실기기 MAC 은 unique — 이미 등록돼 있으면(내 것이든 남의 것이든) 409.
    # 기기 이전은 기존 소유자가 삭제 후 재등록하는 흐름.
    existing = await db.execute(select(Device.id).where(Device.mac_address == payload.mac_address))
    if existing.scalar_one_or_none() is not None:
        raise ConflictException("이미 등록된 MAC 주소입니다")

    device = Device(user_id=user_id, nickname=payload.nickname, mac_address=payload.mac_address)
    db.add(device)
    try:
        await db.commit()
    except IntegrityError as e:  # 동시 등록 레이스 — unique 제약이 최종 방어선
        await db.rollback()
        raise ConflictException("이미 등록된 MAC 주소입니다") from e
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

    if payload.is_connected is False:
        # FE '연결 해제' — DB 플래그만 바꾸면 기기 WS 가 살아있는 동안 가짜 상태가 되므로
        # 서버측에서 WS 를 닫는다. (핸들러 finally 는 이미 빠진 연결이라 DB 를 다시 안 건드림)
        from app.websocket.manager import device_manager

        if await device_manager.close_device(device_id):
            logger.info("device ws closed by disconnect request device_id=%s", device_id)
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
    return await get_owned_or_403(db, Device, device_id, user_id)
