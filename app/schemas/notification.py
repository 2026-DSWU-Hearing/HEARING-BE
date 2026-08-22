from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationItem(BaseModel):
    """감지 하나의 표현. WS `detection` 메시지의 data 와 GET /notifications 의 items 가
    **이 모델 하나를 공유한다**.

    FE 는 WS 로 받은 실시간 이벤트를 목록 캐시 맨 앞에 그대로 끼워 넣고 id 로 중복을 제거한다.
    두 경로의 필드가 하나라도 어긋나면 같은 알림이 두 번 보이거나, 낙관적으로 삽입한 항목의
    id 가 삭제 요청에 실려 나가 서버가 못 알아본다. 손으로 맞춘 dict 두 벌은 언젠가 갈라지므로
    모델 하나로 묶어 갈라지는 것 자체를 불가능하게 만든다.

    confidence 에 널을 허용하지 않는 이유: FE 검증기는 이 값이 널이면 **그 페이지 전체**를
    잘못된 응답으로 보고 목록을 빈 배열로 만든다(항목 하나가 빠지는 게 아니다). 수신 단계
    (DetectionCreate)와 DB 제약으로 널을 막으므로 여기까지 널이 올 수 없다.

    device_id·sound_id·is_read 는 일부러 뺐다 — WS 페이로드에 없는 필드를 목록에만 넣으면
    FE 가 두 경로를 같은 타입으로 못 쓴다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    sound_name: str
    sound_category: str
    source: str
    confidence: float
    location: str | None
    detected_at: datetime


class NotificationListResponse(BaseModel):
    """GET /notifications — 커서 기반 무한 스크롤."""

    items: list[NotificationItem]
    next_cursor: str | None
    has_next: bool


class NotificationDeleteRequest(BaseModel):
    """POST /notifications/delete — 선택 삭제.

    상한 100 은 요청 크기를 묶기 위한 값이다. 화면의 [전체 선택]로 그보다 많아지면
    FE 가 쪼개 보내는 대신 POST /notifications/delete-all 을 쓰면 된다.
    """

    ids: list[int] = Field(min_length=1, max_length=100)


class NotificationDeleteResponse(BaseModel):
    deleted_count: int


class NotificationResponse(BaseModel):
    """PATCH /{id}/read 전용. 목록·WS 와 달리 내부 필드까지 노출한다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int | None  # 기기 삭제 시 SET NULL — 알림 히스토리는 기기보다 오래 산다
    sound_id: int | None
    sound_name: str
    sound_category: str
    source: str
    confidence: float
    location: str | None
    detected_at: datetime
    is_read: bool
