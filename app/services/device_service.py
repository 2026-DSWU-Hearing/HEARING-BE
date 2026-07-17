"""소리 필터링 진입 서비스. 웨어러블(source='device')과 HEARING-AI-SE(source='ai-server')의
감지 결과를 모두 POST /devices/{id}/detections로 받아 처리한다."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictException
from app.core.logger import logger
from app.db.functions import get_or_404, get_owned_or_403
from app.models.device import Device
from app.schemas.device import DetectionCreate, DeviceCreate, DeviceUpdate


async def list_devices(db: AsyncSession, user_id: int) -> list[Device]:
    result = await db.execute(select(Device).where(Device.user_id == user_id))
    return list(result.scalars().all())


async def create_device(db: AsyncSession, user_id: int, payload: DeviceCreate) -> Device:
    # MAC은 서버 설정이 원천이다(Settings 가 정규화 보장). 여러 계정이 같은 물리 기기를
    # 등록해 공유할 수 있으며, 같은 계정의 재등록은 멱등 — 입력한 이름만 반영하고 기존 행을 반환한다.
    device_mac = settings.DEVICE_MAC_ADDRESS
    existing = await _rename_existing_device(db, user_id, device_mac, payload.nickname)
    if existing is not None:
        return existing

    device = Device(user_id=user_id, nickname=payload.nickname, mac_address=device_mac)
    db.add(device)
    try:
        await db.commit()
    except IntegrityError as e:  # 동시 등록 레이스 — uq_devices_user_mac 이 잡아준 쪽을 다시 읽는다(멱등)
        await db.rollback()
        existing = await _rename_existing_device(db, user_id, device_mac, payload.nickname)
        if existing is None:  # unique 충돌인데 행이 없다 — 예상 밖(다른 제약 위반)
            raise ConflictException("기기 등록에 실패했습니다") from e
        return existing
    await db.refresh(device)
    return device


async def _rename_existing_device(
    db: AsyncSession, user_id: int, device_mac: str, nickname: str
) -> Device | None:
    """이 계정의 기존 기기 행이 있으면 등록 요청의 이름을 반영해 반환. 없으면 None.
    다른 MAC 행(서버 MAC 변경 이전의 잔여)이면 계정당 1대 정책으로 409."""
    result = await db.execute(select(Device).where(Device.user_id == user_id))
    existing = result.scalars().first()
    if existing is None:
        return None
    if existing.mac_address != device_mac:
        raise ConflictException("기기는 계정당 한 대만 등록할 수 있습니다 (기존 기기 삭제 후 등록)")
    if existing.nickname != nickname:  # 재등록 = "이 이름으로 쓰겠다" — 이름 무시하면 사용자 입력이 증발한다
        existing.nickname = nickname
        await db.commit()
        await db.refresh(existing)
    return existing


async def update_device(db: AsyncSession, user_id: int, device_id: int, payload: DeviceUpdate) -> Device:
    # is_connected·battery_level 은 기기 WS 수명주기 전용(스키마에서 제거) — PATCH 는 닉네임만.
    device = await _get_owned_device(db, user_id, device_id)
    if payload.nickname is not None:
        device.nickname = payload.nickname
    await db.commit()
    await db.refresh(device)
    return device


async def delete_device(db: AsyncSession, user_id: int, device_id: int) -> None:
    device = await _get_owned_device(db, user_id, device_id)
    mac = device.mac_address
    await db.delete(device)
    await db.commit()

    # 이 MAC 을 등록한 계정이 하나도 안 남았을 때만 하드웨어 WS 를 닫는다
    # (다른 계정이 공유 중이면 연결 유지 — 그들의 is_connected 상태를 깨지 않도록).
    remaining = await db.execute(select(Device.id).where(Device.mac_address == mac).limit(1))
    if remaining.scalar_one_or_none() is None:
        from app.websocket.manager import device_manager

        if await device_manager.close_device(mac):
            logger.info("device ws closed (last registration removed) mac=%s", mac)


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
