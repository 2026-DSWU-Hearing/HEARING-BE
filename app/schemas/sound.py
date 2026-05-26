from pydantic import BaseModel, ConfigDict


class SoundCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class SoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    risk_level: str
    icon_url: str | None
    category: SoundCategoryResponse
