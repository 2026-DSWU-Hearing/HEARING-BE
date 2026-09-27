"""대화(양방향 소통) API 스키마.

필드명은 FE 계약(HEARING-FE src/pages/communication/types/conversationApiTypes.ts)을 그대로 따른다.
그래서 응답은 snake_case(conversation_id, created_at)인데 버블의 inputType 만 camelCase 다 —
FE 가 화면 타입(ChatBubbleTypes)을 그대로 실어 보내기 때문. 여기서 alias 로 받고 alias 로 돌려준다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BubbleDirection = Literal["left", "right"]
BubbleInputType = Literal["text", "stt", "favorite_answer"]

# 문서 없는 상한. 버블 하나가 Text 라 길이는 자유지만, 요청 한 건이 무한정 커지는 건 막는다.
MAX_BUBBLES_PER_CONVERSATION = 1000


class ConversationCreate(BaseModel):
    """POST /api/conversations — 위치 권한 거부·실내면 둘 다 null 로 온다(정상 입력)."""

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class ConversationCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: int = Field(validation_alias="id")
    created_at: datetime


class BubbleIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    direction: BubbleDirection
    input_type: BubbleInputType = Field(alias="inputType")
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, v: str) -> str:
        # FE 도 trim 후 빈 것을 거르지만, 서버가 독립적으로 보장한다 — 공백뿐인 버블은 저장 가치가 없다.
        v = v.strip()
        if not v:
            raise ValueError("content must not be blank")
        return v


class ConversationEndRequest(BaseModel):
    """POST /api/conversations/{id}/end — 대화 전체를 한 번에. 빈 목록은 422:
    FE 는 버블이 없으면 end 대신 DELETE 를 부르기로 했으니(useActiveConversationStore),
    빈 end 가 오면 계약이 어긋난 것이다."""

    bubbles: list[BubbleIn] = Field(min_length=1, max_length=MAX_BUBBLES_PER_CONVERSATION)


class ConversationEnded(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: int = Field(validation_alias="id")
    title: str
    summary: str


class BubbleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    bubble_id: int = Field(validation_alias="id")
    direction: BubbleDirection
    input_type: BubbleInputType = Field(validation_alias="input_type", serialization_alias="inputType")
    content: str
    created_at: datetime


class ConversationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: int = Field(validation_alias="id")
    created_at: datetime
    # 종료 전(진행 중이거나 저장 실패로 버려진 대화)에는 null.
    title: str | None
    summary: str | None
    latitude: float | None
    longitude: float | None
    ended_at: datetime | None


class ConversationDetail(ConversationListItem):
    bubbles: list[BubbleOut]


class ConversationListResponse(BaseModel):
    """GET /api/conversations — 오프셋 페이지네이션(FE 계약). 알림 목록의 커서 방식과 다르지만
    대화는 사용자가 직접 만든 수십 건 규모라 오프셋으로 충분하다."""

    conversations: list[ConversationListItem]
    total: int
    page: int
    limit: int
    has_next: bool
