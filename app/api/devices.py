"""소리 필터링 진입점 API.

POST /devices/{id}/detections는 두 경로(웨어러블, AI서버)가 공유.
caller 구분은 JWT payload의 source 필드로:
  - source = "device"     → 웨어러블 온디바이스 AI
  - source = "ai-server"  → HEARING-AI-SE 서버
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_source, get_current_user_id, get_db
from app.schemas.device import DetectionCreate, DeviceCreate, DeviceResponse, DeviceUpdate
from app.services import device_service

router = APIRouter()


@router.get("", response_model=list[DeviceResponse])
async def list_devices(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await device_service.list_devices(db, user_id)


@router.post("", response_model=DeviceResponse)
async def create_device(payload: DeviceCreate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await device_service.create_device(db, user_id, payload)


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
    ctx: dict = Depends(get_current_source),
    db: AsyncSession = Depends(get_db),
):
    """웨어러블 또는 HEARING-AI-SE가 호출. JWT source 필드로 caller 식별."""
    await device_service.handle_detection(db, device_id, payload, source=ctx["source"])
    return {"ok": True}
