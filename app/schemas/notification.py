from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    sound_id: int | None
    sound_name: str
    sound_category: str
    risk_level: str
    source: str
    confidence: float | None
    location: str | None
    detected_at: datetime
    is_read: bool
