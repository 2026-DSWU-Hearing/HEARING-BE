from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


Direction = Literal["FRONT", "BACK", "LEFT", "RIGHT", "UNKNOWN"]


def normalize_mac(mac: str) -> str:
    """서버 설정(Settings validator)과 WS 접속(resolve_registered_mac) 양쪽에서 동일 정규화 —
    대소문자/공백 차이로 물리 기기를 못 찾아 4404 가 나는 일이 없도록."""
    return mac.strip().upper()


class DeviceConnectRequest(BaseModel):
    """POST /devices/connect — [기기 연결] 버튼.
    온보딩은 입력한 기기 이름을 함께 보내고, 설정의 [이 계정으로 전환]은 body 없이 호출한다
    (이름 생략 시 내 계정의 기존 이름 유지)."""

    nickname: str | None = Field(default=None, min_length=1, max_length=50)


class DeviceUpdate(BaseModel):
    """PATCH 는 닉네임만 — 내 계정의 기기 이름(users.device_nickname)만 바뀐다.
    is_connected·battery_level 은 기기 WS 수명주기가 진실 원천이라 클라이언트가 쓸 수 없다
    (과거 FE 가 PATCH is_connected:true 로 만든 '유령 연결' 재발 방지.
    모르는 필드는 pydantic 기본 동작으로 무시되므로 구버전 FE 요청도 깨지지 않는다)."""

    nickname: str | None = Field(default=None, min_length=1, max_length=50)


class DeviceResponse(BaseModel):
    """요청 계정 기준으로 계산되는 뷰 — nickname 은 내 계정이 지은 이름(없으면 기본 표시명),
    is_active_user 는 알림·진동이 지금 내 계정으로 오는지."""

    id: int
    nickname: str
    battery_level: int | None
    is_connected: bool
    is_active_user: bool
    last_seen_at: datetime | None


class DetectionCreate(BaseModel):
    """POST /devices/{id}/detections — 웨어러블/AI서버 공통 페이로드.

    detected_at 은 타임존을 강제한다 — 없이 오면 timestamptz 컬럼이 UTC 로 간주해 KST 기준
    9시간 어긋난 시각이 조용히 저장되고, 화면에는 그럴듯한 시각이 찍혀 알아채기 어렵다.

    반대로 confidence 는 **일부러 필수로 두지 않는다**. 화면에 표시하지도 않는 메타데이터
    하나가 없다고 422 로 거절하면 그 감지가 통째로 사라지는데, 청각보조 앱에서 화재 경보를
    잃는 손해가 훨씬 크다. 없이 들어오면 널로 저장하고 경고 로그만 남긴다
    (notification_service.handle_detection) — 감지는 살리고 프로듀서 문제는 드러낸다.
    """

    sound_id: int | None = None
    sound_name: str
    sound_category: str
    # allow_inf_nan=False: NaN 은 JSON 에 표준 표현이 없어 FE 의 JSON.parse 가 던진다.
    # 널은 허용하되 NaN/Infinity 는 계속 막는다 — 전자는 '값 없음'이지만 후자는 깨진 값이다.
    confidence: float | None = Field(default=None, allow_inf_nan=False)
    detected_at: AwareDatetime
    direction: Direction = "UNKNOWN"
    latitude: float | None = None
    longitude: float | None = None
