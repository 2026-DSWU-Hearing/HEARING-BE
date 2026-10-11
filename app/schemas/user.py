from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# disability_type 정본 (대문자). FE 설정 화면이 이 값을 그대로 보낸다.
DISABILITY_TYPES = frozenset({"HARD_OF_HEARING", "DEAF"})


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str
    disability_type: str | None
    haptic_strength: int
    do_not_disturb: bool
    push_enabled: bool
    emergency_alert_enabled: bool
    terms_agreed: bool
    location_agreed: bool


class UserUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=50)
    disability_type: str | None = None

    @field_validator("disability_type")
    @classmethod
    def _normalize_disability_type(cls, v: str | None) -> str | None:
        """FE 온보딩(소문자)·설정(대문자) 어느 쪽이 와도 정본(대문자)으로 저장한다."""
        if v is None:
            return None
        normalized = v.strip().upper()
        if normalized not in DISABILITY_TYPES:
            raise ValueError("disability_type must be one of: HARD_OF_HEARING, DEAF")
        return normalized


class HapticUpdate(BaseModel):
    haptic_strength: int = Field(ge=0, le=100)


class DoNotDisturbUpdate(BaseModel):
    do_not_disturb: bool


class PushEnabledUpdate(BaseModel):
    push_enabled: bool


class EmergencyAlertUpdate(BaseModel):
    emergency_alert_enabled: bool


class FcmTokenUpdate(BaseModel):
    fcm_token: str


class AgreementUpdate(BaseModel):
    """PATCH /users/me/agreement — 온 필드만 갱신한다.

    둘 다 선택인 이유: 양방향 소통 모달은 location_agreed 하나만 보낸다. terms_agreed 가 필수면
    FE 가 이미 true 인 값을 매번 다시 보내야 하고, 실수로 false 를 보내면 약관 동의가 풀린다.
    """

    terms_agreed: bool | None = None
    location_agreed: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "AgreementUpdate":
        if self.terms_agreed is None and self.location_agreed is None:
            raise ValueError("terms_agreed 또는 location_agreed 중 하나는 있어야 합니다")
        return self
