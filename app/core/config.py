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

    # 실물 웨어러블 기기의 MAC — 물리 기기 행(1개)의 원천값. 기동/devinit 의
    # ensure_physical_device 가 이 값으로 행을 만들거나(기기 교체 시) MAC 을 갱신한다.
    DEVICE_MAC_ADDRESS: str = "44:1B:F6:D4:47:F0"

    @field_validator("DEVICE_MAC_ADDRESS")
    @classmethod
    def _normalize_device_mac(cls, v: str) -> str:
        # 저장(ensure)과 WS 조회가 전부 정규화된 값 기준이므로 원천에서 한 번에 맞춘다
        # (.env 에 소문자/공백으로 넣어도 기기 상태 갱신이 어긋나지 않도록).
        from app.schemas.device import normalize_mac

        return normalize_mac(v)

    # HEARING-MODEL(AI) 의 **분석 전용** WS. livesound(실시간 소리 감지) 릴레이가 여기에 붙는다.
    # 기존 /ws(ESP32용)와 달리 알림·쿨다운·백엔드 POST 부수효과가 없어야 한다 — 그쪽에 붙이면
    # 화면만 보는 사용자 때문에 넥밴드 사용자에게 실제 알림·진동이 나간다.
    AI_SERVER_WS_URL: str = "ws://localhost:8001/ws/analyze"
    # 세션 시작 시 AI 서버에 붙는 데 허용하는 시간. 왕복 타임아웃과 반드시 **분리**한다 —
    # 클라이언트는 start 를 보낸 뒤 ready 를 5초까지만 기다리는데(FE READY_TIMEOUT_MS),
    # 접속 대기가 그만큼 길면 "분석 서버에 연결할 수 없습니다" 안내가 도착하기 전에
    # 클라이언트가 먼저 끊어서 사용자는 원인을 알 수 없는 침묵만 본다.
    AI_CONNECT_TIMEOUT_SECONDS: float = 2.0
    # AI 왕복이 이 시간을 넘으면 그 창은 버린다(오래된 오디오는 화면에 쓸모가 없다).
    # 이쪽은 ready 이후라 클라이언트의 ready 대기와 무관하다.
    AI_ANALYZE_TIMEOUT_SECONDS: float = 5.0

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
