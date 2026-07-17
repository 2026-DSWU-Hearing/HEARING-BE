from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int | None  # 기기 삭제 시 SET NULL — 알림 히스토리는 기기보다 오래 산다
    sound_id: int | None
    sound_name: str
    sound_category: str
    source: str
    confidence: float | None
    location: str | None
    detected_at: datetime
    is_read: bool
