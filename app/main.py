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
    # 앱(프론트) API는 /api/v1 하위. 흐름 A의 devices/notifications/websocket(웨어러블·AI서버)은
    # 기존 경로 유지 — 외부 클라이언트 계약을 깨지 않기 위함.
    app.include_router(modes.router, prefix="/api/v1/modes", tags=["modes"])
    app.include_router(sounds.router, prefix="/api/v1/sounds", tags=["sounds"])
    app.include_router(devices.router, prefix="/devices", tags=["devices"])
    app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
    app.include_router(websocket.router, tags=["websocket"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
