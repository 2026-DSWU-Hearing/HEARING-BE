from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 기본값 없음 — 누락 시 시작 단계에서 ValidationError(fail-closed). 환경변수/.env 에 반드시 설정.
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    GOOGLE_CLIENT_ID: str = ""

    FCM_CREDENTIALS_PATH: str = "firebase-credentials.json"

    # MVP 개발용: True 면 인증 헤더 없이 DEV_USER_ID 로 통과 (운영에서는 반드시 False)
    DEV_AUTH_BYPASS: bool = False
    DEV_USER_ID: int = 1

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:4173"]

    @field_validator("JWT_SECRET")
    @classmethod
    def _strong_jwt_secret(cls, v: str) -> str:
        # 공개 레포의 약한 기본값(예: "change-me")으로 토큰이 위조되는 사고 방지 — 충분히 긴 랜덤값 강제.
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be a strong random value (>= 32 chars)")
        return v


settings = Settings()
