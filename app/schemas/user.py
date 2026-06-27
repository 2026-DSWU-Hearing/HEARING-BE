from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str
    disability_type: str | None
    haptic_strength: int
    do_not_disturb: bool
    push_enabled: bool


class UserUpdate(BaseModel):
    nickname: str | None = None
    disability_type: str | None = None


class HapticUpdate(BaseModel):
    haptic_strength: int = Field(ge=0, le=100)


class DoNotDisturbUpdate(BaseModel):
    do_not_disturb: bool


class PushEnabledUpdate(BaseModel):
    push_enabled: bool


class FcmTokenUpdate(BaseModel):
    fcm_token: str


class AgreementUpdate(BaseModel):
    terms_agreed: bool
