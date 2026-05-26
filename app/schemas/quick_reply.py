from pydantic import BaseModel, ConfigDict


class QuickReplyCreate(BaseModel):
    text: str
    order: int = 0


class QuickReplyUpdate(BaseModel):
    text: str | None = None
    order: int | None = None


class QuickReplyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    order: int
