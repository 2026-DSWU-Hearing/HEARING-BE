from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 배포 환경 구분. prod 에서 DEV_AUTH_BYPASS 가 켜져 있으면 기동 자체를 거부한다(아래 validator).
    # Literal 이라 오타(예: "production")도 시작 단계에서 잡힌다.
    ENVIRONMENT: Literal["dev", "prod"] = "dev"

    # 기본값 없음 — 누락 시 시작 단계에서 ValidationError(fail-closed). 환경변수/.env 에 반드시 설정.
    DATABASE_URL: str = Field(min_length=1)
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    GOOGLE_CLIENT_ID: str = ""

    # 실물 웨어러블 기기의 MAC. 수동 등록 시 서버가 이 값을 저장하며, 여러 계정이
    # 같은 물리 기기를 등록해 공유할 수 있다. 기기가 바뀌면 여기(.env)만 바꾸면 된다.
    DEVICE_MAC_ADDRESS: str = "44:1B:F6:D4:47:F0"

    @field_validator("DEVICE_MAC_ADDRESS")
    @classmethod
    def _normalize_device_mac(cls, v: str) -> str:
        # 저장(등록·devinit)과 WS 조회가 전부 정규화된 값 기준이므로 원천에서 한 번에 맞춘다
        # (.env 에 소문자/공백으로 넣어도 기기 상태 갱신이 어긋나지 않도록).
        from app.schemas.device import normalize_mac

        return normalize_mac(v)

    FCM_CREDENTIALS_PATH: str = "firebase-credentials.json"

    # 인메모리-임시 저장소 (게스트 rate limit, refresh 토큰 블랙리스트). PostgreSQL=관계형-영구와 역할 분리.
    REDIS_URL: str = "redis://localhost:6379/0"
    # 게스트 로그인 IP당 시간당 허용 횟수 (호출마다 유저+샘플데이터가 생성되므로 봇 방어 필요)
    GUEST_RATE_LIMIT_PER_HOUR: int = 10

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

    @model_validator(mode="after")
    def _no_auth_bypass_outside_dev(self) -> "Settings":
        # 인증 우회는 로컬 개발 전용. .env 가 그대로 서버에 올라가는 사고를 기동 실패로 막는다.
        if self.DEV_AUTH_BYPASS and self.ENVIRONMENT != "dev":
            raise ValueError("DEV_AUTH_BYPASS must be false when ENVIRONMENT is not 'dev'")
        return self


settings = Settings()
