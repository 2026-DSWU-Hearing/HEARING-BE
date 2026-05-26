from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConversationCreate(BaseModel):
    title: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class BubbleCreate(BaseModel):
    speaker: str
    text: str


class BubbleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    speaker: str
    text: str
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    location: str | None
    started_at: datetime
    ended_at: datetime | None
    bubbles: list[BubbleResponse] = []
