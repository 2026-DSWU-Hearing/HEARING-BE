"""기기 API — 물리 기기(넥밴드)는 1대, 응답은 항상 요청 계정 기준 뷰다.

POST /devices/connect 가 유일한 전환 지점: 하드웨어 WS 접속 여부를 즉시 확인해
성공/실패를 바로 응답하고(폴링 불필요), 성공 시 이 계정이 현재 사용자(active user)가 된다.

POST /devices/{id}/detections 는 두 경로(웨어러블, AI서버)가 공유.
caller 구분은 JWT payload의 source 필드로:
  - source = "device"     → 웨어러블 온디바이스 AI
  - source = "ai-server"  → HEARING-AI-SE 서버
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AccessTokenClaims
from app.db.dependencies import get_current_source, get_current_user_id, get_db
from app.schemas.device import DetectionCreate, DeviceConnectRequest, DeviceResponse, DeviceUpdate
from app.services import device_service

router = APIRouter()


@router.get("", response_model=list[DeviceResponse])
async def list_devices(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await device_service.list_devices(db, user_id)


@router.post("/connect", response_model=DeviceResponse)
async def connect_device(
    payload: DeviceConnectRequest | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """[기기 연결] — 온보딩은 {nickname} 을 보내고, 설정의 [이 계정으로 전환]은 body 없이 호출.
    하드웨어 미접속이면 409."""
    nickname = payload.nickname if payload else None
    return await device_service.connect_device(db, user_id, nickname)


@router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: int, payload: DeviceUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await device_service.update_device(db, user_id, device_id, payload)


@router.delete("/{device_id}")
async def delete_device(device_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await device_service.delete_device(db, user_id, device_id)
    return {"ok": True}


@router.post("/{device_id}/detections")
async def post_detection(
    device_id: int,
    payload: DetectionCreate,
    ctx: AccessTokenClaims = Depends(get_current_source),
    db: AsyncSession = Depends(get_db),
):
    """웨어러블 또는 HEARING-AI-SE가 호출. JWT source 필드로 caller 식별."""
    await device_service.handle_detection(db, device_id, payload, source=ctx.source)
    return {"ok": True}
