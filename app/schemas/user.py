from pydantic import BaseModel, ConfigDict, Field, computed_field

# UI 슬라이더(0~100)를 실제 하드웨어 진동값으로 환산하는 규칙.
# 일반 진동은 최대 80까지만 쓰고(여유분 확보), 긴급 부스트가 켜지면 남은 여유분까지 풀어 100을 쓴다.
NORMAL_HAPTIC_CEILING = 0.8  # UI 100 → 하드웨어 80
EMERGENCY_HAPTIC_VALUE = 100


def normal_haptic_hw(haptic_strength: int) -> int:
    """일반 알림의 실제 하드웨어 진동값 (UI값 * 0.8)."""
    return round(haptic_strength * NORMAL_HAPTIC_CEILING)


def emergency_haptic_hw(haptic_strength: int, emergency_haptic_boost: bool) -> int:
    """긴급 알림의 실제 하드웨어 진동값. 부스트가 꺼져 있으면 일반과 동일."""
    if emergency_haptic_boost:
        return EMERGENCY_HAPTIC_VALUE
    return normal_haptic_hw(haptic_strength)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str
    disability_type: str | None
    haptic_strength: int
    emergency_haptic_boost: bool
    do_not_disturb: bool
    push_enabled: bool
    terms_agreed: bool

    @computed_field
    @property
    def normal_haptic_hw(self) -> int:
        """일반 알림의 실제 하드웨어 진동값 (앱/기기가 이 값을 그대로 사용)."""
        return normal_haptic_hw(self.haptic_strength)

    @computed_field
    @property
    def emergency_haptic_hw(self) -> int:
        """긴급 알림의 실제 하드웨어 진동값."""
        return emergency_haptic_hw(self.haptic_strength, self.emergency_haptic_boost)


class UserUpdate(BaseModel):
    nickname: str | None = None
    disability_type: str | None = None


class HapticUpdate(BaseModel):
    haptic_strength: int = Field(ge=0, le=100)


class EmergencyHapticBoostUpdate(BaseModel):
    emergency_haptic_boost: bool


class DoNotDisturbUpdate(BaseModel):
    do_not_disturb: bool


class PushEnabledUpdate(BaseModel):
    push_enabled: bool


class FcmTokenUpdate(BaseModel):
    fcm_token: str


class AgreementUpdate(BaseModel):
    terms_agreed: bool
