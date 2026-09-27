from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuickReplyWrite(BaseModel):
    """POST / PUT 공용 바디 — 문구 하나뿐. 빈 문구는 422(FE 도 걸러서 보내지만 서버가 독립 보장)."""

    content: str = Field(min_length=1, max_length=200)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("content must not be blank")
        return v


class QuickReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reply_id: int = Field(validation_alias="id")
    content: str


class QuickReplyCreated(QuickReplyOut):
    created_at: datetime


class QuickReplyListResponse(BaseModel):
    quick_replies: list[QuickReplyOut]
