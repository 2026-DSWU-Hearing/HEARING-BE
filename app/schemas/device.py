from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Direction = Literal["FRONT", "BACK", "LEFT", "RIGHT", "UNKNOWN"]


def normalize_mac(mac: str) -> str:
    """등록(DeviceCreate)과 WS 접속(resolve_registered_mac) 양쪽에서 동일 정규화 —
    대소문자/공백 차이로 등록된 기기를 못 찾아 4404 가 나는 일이 없도록."""
    return mac.strip().upper()


class DeviceCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=50)


class DeviceUpdate(BaseModel):
    """PATCH 는 닉네임만. is_connected·battery_level 은 기기 WS 수명주기가 진실 원천이라
    클라이언트가 쓸 수 없다 — 과거 FE 가 PATCH is_connected:true 로 만든 '유령 연결' 재발 방지.
    (모르는 필드는 pydantic 기본 동작으로 무시되므로 구버전 FE 요청도 깨지지 않는다)"""

    nickname: str | None = Field(default=None, min_length=1, max_length=50)


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
    direction: Direction = "UNKNOWN"
    latitude: float | None = None
    longitude: float | None = None
