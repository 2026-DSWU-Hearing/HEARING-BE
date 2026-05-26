from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str
    disability_type: str | None
    haptic_strength: int
    do_not_disturb: bool


class UserUpdate(BaseModel):
    nickname: str | None = None
    disability_type: str | None = None


class HapticUpdate(BaseModel):
    haptic_strength: int


class DoNotDisturbUpdate(BaseModel):
    do_not_disturb: bool


class FcmTokenUpdate(BaseModel):
    fcm_token: str


class AgreementUpdate(BaseModel):
    terms_agreed: bool
