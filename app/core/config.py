from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/hearing"
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    GOOGLE_CLIENT_ID: str = ""

    RTZR_CLIENT_ID: str = ""
    RTZR_CLIENT_SECRET: str = ""
    RTZR_API_BASE: str = "https://openapi.vito.ai"

    FCM_CREDENTIALS_PATH: str = "firebase-credentials.json"

    KAKAO_REST_API_KEY: str = ""

    CORS_ORIGINS: list[str] = ["*"]


settings = Settings()
