from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.handlers import register_exception_handlers
from app.core.logger import logger
from app.core.middleware import setup_middleware
from app.api import auth, users, modes, sounds, devices, notifications, websocket
from app.websocket.device_handler import reset_all_connections


@asynccontextmanager
async def lifespan(app: FastAPI):
    # WS 는 서버 재시작을 살아남지 못하므로 부팅 직후엔 연결된 기기가 없는 게 진실 —
    # 크래시·과거 데이터로 남은 is_connected=true 를 리셋한다(기기 상태의 진실 원천은 WS 수명주기).
    await reset_all_connections()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="HEARING-BE", version="0.1.0", lifespan=lifespan)

    # prod 에서는 config validator 가 기동을 막지만, dev 에서도 켜져 있음을 부팅 로그로 상기시킨다.
    if settings.DEV_AUTH_BYPASS:
        logger.warning(
            "DEV_AUTH_BYPASS is ON — tokenless requests run as user id=%s. Never use outside local dev.",
            settings.DEV_USER_ID,
        )

    setup_middleware(app)
    register_exception_handlers(app)

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(users.router, prefix="/users", tags=["users"])
    # 전 API 루트 경로(prefix 없음). FE가 modes/sounds 호출에서 /api/v1 을 제거(HEARING-FE 7fd26cc)함에
    # 따라 백엔드도 맞춤 — 이제 앱 API와 흐름 A(devices/notifications/websocket) 모두 루트로 통일.
    app.include_router(modes.router, prefix="/modes", tags=["modes"])
    app.include_router(sounds.router, prefix="/sounds", tags=["sounds"])
    app.include_router(devices.router, prefix="/devices", tags=["devices"])
    app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
    app.include_router(websocket.router, tags=["websocket"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
