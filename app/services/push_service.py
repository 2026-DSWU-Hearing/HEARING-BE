"""FCM 푸시 알림. firebase-admin SDK 사용."""

import asyncio

from app.core.config import settings
from app.core.logger import logger
from app.models.notification import Notification

_initialized = False


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(settings.FCM_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
        _initialized = True
    except Exception as e:
        logger.warning("FCM init failed: %s", e)


async def send_detection_push(fcm_token: str, notification: Notification) -> None:
    _ensure_initialized()
    try:
        from firebase_admin import messaging

        message = messaging.Message(
            token=fcm_token,
            notification=messaging.Notification(
                title=notification.sound_name,
                body=notification.sound_category,
            ),
            data={
                "notification_id": str(notification.id),
                "sound_name": notification.sound_name,
                "source": notification.source,
            },
        )
        # firebase-admin 의 messaging.send 는 동기(블로킹) 호출 → 스레드로 보내 이벤트 루프 블로킹 방지
        await asyncio.to_thread(messaging.send, message)
    except Exception as e:
        logger.error("FCM send failed: %s", e)
