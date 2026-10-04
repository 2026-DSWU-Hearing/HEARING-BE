from pydantic import BaseModel


# --- 프론트(home) 읽기 응답 계약: snake_case + 래핑 ---


class ModeListItem(BaseModel):
    mode_id: int
    name: str
    icon: str
    is_active: bool


class ModeListResponse(BaseModel):
    modes: list[ModeListItem]


class ModeSoundItem(BaseModel):
    """모드 응답(상세·생성·수정·소리 교체)에 공통으로 쓰는 소리 1건.

    생성/수정 응답에도 category·is_active 를 내려줘야 FE 가 이전 캐시로 is_active 를
    추측하지 않고 응답을 그대로 캐시에 넣을 수 있다.
    """

    sound_id: int
    name: str
    category: str  # 카테고리명(문자열) — 프론트 상세 화면 계약
    is_active: bool  # 모드 안에서 이 소리의 on/off (off=회색·감지 제외). 기본 on


class ModeDetailResponse(BaseModel):
    mode_id: int
    name: str
    icon: str
    is_active: bool
    sounds: list[ModeSoundItem]


# --- 프론트(home) 쓰기 요청/응답 계약 ---


class ModeSoundInput(BaseModel):
    sound_id: int
    name: str | None = None  # 프론트가 보내지만 서버는 sound_id만 사용


class ModeWriteRequest(BaseModel):
    """모드 생성(POST)·전체 수정(PUT) 공통 요청 바디. 응답은 ModeWriteResponse."""

    name: str
    icon: str
    sounds: list[ModeSoundInput]


class ModeSoundsUpdateRequest(BaseModel):
    sounds: list[ModeSoundInput]


class ModeWriteResponse(BaseModel):
    mode_id: int
    name: str
    icon: str
    sounds: list[ModeSoundItem]


class ModeActivateResponse(BaseModel):
    mode_id: int
    is_active: bool


class ModeSoundsResponse(BaseModel):
    mode_id: int
    sounds: list[ModeSoundItem]


class ModeSoundActiveUpdate(BaseModel):
    is_active: bool


class ModeSoundActiveResponse(BaseModel):
    mode_id: int
    sound_id: int
    is_active: bool


# --- 모드 아이콘 카탈로그(참조) 응답 계약 ---


class ModeIconItem(BaseModel):
    mode_id: int
    name_ko: str
    name_key: str
    icon_key: str


class ModeIconListResponse(BaseModel):
    icons: list[ModeIconItem]
