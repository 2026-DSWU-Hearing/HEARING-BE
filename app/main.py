from fastapi import FastAPI

from app.core.config import settings
from app.core.handlers import register_exception_handlers
from app.core.middleware import setup_middleware
from app.api import auth, users, modes, sounds, devices, notifications, conversations, quick_replies, websocket


def create_app() -> FastAPI:
    app = FastAPI(title="HEARING-BE", version="0.1.0")

    setup_middleware(app)
    register_exception_handlers(app)

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(modes.router, prefix="/modes", tags=["modes"])
    app.include_router(sounds.router, prefix="/sounds", tags=["sounds"])
    app.include_router(devices.router, prefix="/devices", tags=["devices"])
    app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
    app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
    app.include_router(quick_replies.router, prefix="/quick-replies", tags=["quick-replies"])
    app.include_router(websocket.router, tags=["websocket"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
