from fastapi import FastAPI

from app.core.handlers import register_exception_handlers
from app.core.middleware import setup_middleware
from app.api import auth, users, modes, sounds, devices, notifications, websocket


def create_app() -> FastAPI:
    app = FastAPI(title="HEARING-BE", version="0.1.0")

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
