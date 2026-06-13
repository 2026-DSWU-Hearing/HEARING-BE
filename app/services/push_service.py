"""FCM 푸시 알림. firebase-admin SDK 사용."""

import asyncio

from app.core.config import settings
from app.core.logger import logger
from app.models.notification import Notification

_initialized = False


class UnregisteredFcmTokenError(Exception):
    """Raised when FCM no longer recognizes a registration token."""


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
    from firebase_admin import messaging

    try:
        # notification payload 를 빼고 data-only 로 보낸다.
        # 웹 PWA background 에서 notification payload 가 있으면 브라우저가 알림을 자동 표시하고
        # 서비스워커 onBackgroundMessage 도 showNotification 으로 1개 더 그려서 알림이 2개 뜬다.
        # data-only 면 브라우저 자동 표시가 사라져 서비스워커가 그린 알림 1개만 남는다.
        message = messaging.Message(
            token=fcm_token,
            data={
                "title": notification.sound_name,
                "body": f"[{notification.risk_level}] {notification.sound_category}",
                "notification_id": str(notification.id),
                "sound_name": notification.sound_name,
                "source": notification.source,
            },
        )
        # firebase-admin 의 messaging.send 는 동기(블로킹) 호출 → 스레드로 보내 이벤트 루프 블로킹 방지
        await asyncio.to_thread(messaging.send, message)
    except messaging.UnregisteredError as error:
        logger.warning("FCM token is unregistered")
        raise UnregisteredFcmTokenError from error
    except Exception as e:
        logger.error("FCM send failed: %s", e)
