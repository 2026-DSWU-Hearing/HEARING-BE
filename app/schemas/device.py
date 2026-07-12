from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_mac(mac: str) -> str:
    """등록(DeviceCreate)과 WS 접속(resolve_device_id) 양쪽에서 동일 정규화 —
    대소문자/공백 차이로 등록된 기기를 못 찾아 4404 가 나는 일이 없도록."""
    return mac.strip().upper()


class DeviceCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=50)
    mac_address: str = Field(min_length=1, max_length=50)

    @field_validator("mac_address")
    @classmethod
    def _normalize_mac(cls, v: str) -> str:
        return normalize_mac(v)


class DeviceUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=50)
    battery_level: int | None = Field(default=None, ge=0, le=100)
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
    confidence: float | None = None
    detected_at: datetime
    latitude: float | None = None
    longitude: float | None = None
