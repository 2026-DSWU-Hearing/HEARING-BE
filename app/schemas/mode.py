from pydantic import BaseModel, ConfigDict

from app.schemas.sound import SoundResponse


class ModeCreate(BaseModel):
    name: str
    icon: str
    sound_ids: list[int]


class ModeUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None


class ModeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    icon: str
    is_active: bool
    sounds: list[SoundResponse] = []


class ModeSoundsUpdate(BaseModel):
    sound_ids: list[int]
