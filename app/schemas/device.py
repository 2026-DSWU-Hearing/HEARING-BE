from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeviceCreate(BaseModel):
    nickname: str
    mac_address: str


class DeviceUpdate(BaseModel):
    nickname: str | None = None
    battery_level: int | None = None
    is_connected: bool | None = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    mac_address: str
    battery_level: int | None
    is_connected: bool
    last_seen_at: datetime | None


class DetectionCreate(BaseModel):
    """POST /devices/{id}/detections — 웨어러블/AI서버 공통 페이로드."""

    sound_id: int | None = None
    sound_name: str
    sound_category: str
    risk_level: str
    confidence: float | None = None
    detected_at: datetime
    latitude: float | None = None
    longitude: float | None = None
