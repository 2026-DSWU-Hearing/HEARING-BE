from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/hearing"

    JWT_SECRET: str = "change-me"
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


settings = Settings()
