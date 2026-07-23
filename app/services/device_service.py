"""기기 서비스 — 물리 기기(넥밴드)는 1대뿐이라 DB 행도 1개만 둔다.

알림·진동을 받는 사람은 그 행의 active_user_id 한 명(= 마지막으로 [기기 연결]을
누른 계정)이고, 전환은 오직 connect 에서만 일어난다(로그인은 아무것도 바꾸지 않는다).
기기 이름은 계정별 데이터(users.device_nickname) — 같은 기기를 계정마다 다른 이름으로 부른다.
웨어러블(source='device')과 HEARING-AI-SE(source='ai-server')의 감지 결과는 모두
POST /devices/{id}/detections 로 받는다.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictException, NotFoundException
from app.core.logger import logger
from app.db.functions import get_or_404
from app.models.device import Device
from app.models.user import User
from app.schemas.device import DetectionCreate, DeviceResponse, DeviceUpdate

THE_DEVICE_ID = 1  # 물리 기기 행의 고정 id — AI 서버 .env 의 DEVICE_ID 가 이 값으로 감지를 쏜다
DEFAULT_DEVICE_NICKNAME = "Hear:ing NeckBand"  # 계정이 아직 이름을 안 지었을 때의 표시명


async def ensure_physical_device(db: AsyncSession) -> Device:
    """물리 기기 행(id=THE_DEVICE_ID) get-or-create. 서버 기동·devinit 이 부르고 조회 경로도
    이 함수를 거치므로 행이 없어도 자가 치유된다. .env 의 MAC 이 바뀌면(기기 교체) 행을
    새로 만들지 않고 MAC 만 갱신한다 — 알림 히스토리의 device_id 참조가 끊기지 않도록."""
    mac = settings.DEVICE_MAC_ADDRESS
    device = await db.get(Device, THE_DEVICE_ID)
    if device is None:
        device = Device(id=THE_DEVICE_ID, mac_address=mac)
        db.add(device)
        try:
            await db.commit()
        except IntegrityError:  # 동시 생성 레이스 — 먼저 만든 쪽을 읽는다
            await db.rollback()
            device = await db.get(Device, THE_DEVICE_ID)
        else:
            await db.refresh(device)
    elif device.mac_address != mac:
        device.mac_address = mac
        await db.commit()
        await db.refresh(device)
    return device


async def list_devices(db: AsyncSession, user_id: int) -> list[DeviceResponse]:
    """항상 길이 1 — FE 설정 화면이 이 응답을 폴링해 연결·배터리·현재 사용자 여부를 본다."""
    device = await ensure_physical_device(db)
    user = await get_or_404(db, User, user_id)
    return [_to_response(device, user)]


async def connect_device(db: AsyncSession, user_id: int, nickname: str | None) -> DeviceResponse:
    """[기기 연결] — 하드웨어가 지금 서버 WS 에 붙어 있는지 즉시 확인하고, 붙어 있으면
    이 계정을 현재 사용자로 전환한다(다른 계정이 쓰던 중이어도 덮어씀 — 합의된 정책).
    폴링 없이 이 응답 하나로 온보딩의 성공/실패가 결정된다."""
    from app.websocket.manager import device_manager

    device = await ensure_physical_device(db)
    user = await get_or_404(db, User, user_id)
    if not device_manager.is_connected(device.mac_address):
        raise ConflictException("기기가 서버에 연결되어 있지 않습니다. 기기의 전원과 네트워크를 확인해 주세요.")

    device.active_user_id = user_id
    if nickname is not None:
        user.device_nickname = nickname
    await db.commit()
    await db.refresh(device)
    logger.info("device active user switched to user_id=%s", user_id)
    return _to_response(device, user)


async def update_device(
    db: AsyncSession, user_id: int, device_id: int, payload: DeviceUpdate
) -> DeviceResponse:
    device = await _get_physical_device_or_404(db, device_id)
    user = await get_or_404(db, User, user_id)
    if payload.nickname is not None:  # 내 계정의 이름만 바뀐다 — 다른 계정 화면엔 영향 없음
        user.device_nickname = payload.nickname
        await db.commit()
    return _to_response(device, user)


async def delete_device(db: AsyncSession, user_id: int, device_id: int) -> None:
    """'삭제'의 의미 = 내 계정에서 연결 해제. 내가 현재 사용자면 포인터만 비운다(이름은 유지).
    하드웨어 WS 는 닫지 않는다 — 다음 사용자가 [기기 연결]을 바로 누를 수 있어야 한다."""
    device = await _get_physical_device_or_404(db, device_id)
    if device.active_user_id == user_id:
        device.active_user_id = None
        await db.commit()


async def handle_detection(
    db: AsyncSession,
    device_id: int,
    payload: DetectionCreate,
    source: str,
) -> None:
    """소리 필터링 흐름 진입점.

    1) JWT source 확인 (caller가 이미 검증, 여기서는 값만 사용)
    2) Device(물리 행) 존재 확인 → active_user 파악
    3) 현재 사용자가 없으면 스킵, 있으면 notification_service 에 위임 (활성 모드 필터 + 저장 + 푸시)
    """
    from app.services import notification_service

    device = await get_or_404(db, Device, device_id)
    if device.active_user_id is None:
        logger.info(
            "detection dropped (no active user) device_id=%s sound=%s", device_id, payload.sound_name
        )
        return
    logger.info(
        "detection received device_id=%s active_user_id=%s source=%s sound=%s",
        device_id, device.active_user_id, source, payload.sound_name,
    )
    await notification_service.handle_detection(
        db=db,
        user_id=device.active_user_id,
        device=device,
        payload=payload,
        source=source,
    )


def _to_response(device: Device, user: User) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        nickname=user.device_nickname or DEFAULT_DEVICE_NICKNAME,
        battery_level=device.battery_level,
        is_connected=device.is_connected,
        is_active_user=device.active_user_id == user.id,
        last_seen_at=device.last_seen_at,
    )


async def _get_physical_device_or_404(db: AsyncSession, device_id: int) -> Device:
    device = await ensure_physical_device(db)
    if device_id != device.id:
        raise NotFoundException("Device not found")
    return device
