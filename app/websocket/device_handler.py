"""하드웨어(ESP32) WS 핸들러. /ws/devices?token={device_token}&mac={MAC}

기기 WS 수명주기가 is_connected 의 진실 원천:
  접속 → is_connected=True, 해제 → False (+ last_seen_at 갱신)
  {"type": "status"} 수신 → battery_level·last_seen_at 갱신
  (connection_type 은 FE 미표시라 로그만 남긴다)
물리 기기 행은 1개뿐이라(단일 행 모델) 갱신은 MAC 으로 그 행을 찾는다.
[기기 연결] 버튼의 즉시 확인은 device_manager.is_connected 가 담당한다.
진동 명령(send_vibrate)은 notification_service 가 매칭 성공 시 호출한다.

기기 설정(settings_update) — 넥밴드의 온디바이스 AI 가 백엔드 없이도 판단하려면 설정을
기기가 직접 알고 있어야 한다. 세 값을 항상 함께 보낸다:
  {"type":"settings_update","emergency_alert_enabled":bool,"do_not_disturb":bool,"haptic_strength":0~100}
보내는 시점: 기기 접속 시 1회 + 현재 사용자가 설정을 바꿀 때 + 현재 사용자가 바뀔 때.
설정은 계정별이고 넥밴드는 공유 기기라 **현재 사용자(active user)의 값만** 보낸다.
"""

import json
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from app.core.logger import logger
from app.db.session import AsyncSessionLocal
from app.models.device import Device
from app.models.user import User
from app.schemas.device import Direction, normalize_mac
from app.websocket.manager import device_manager


async def resolve_registered_mac(mac: str) -> str | None:
    """접속 MAC → 물리 기기 행의 정규화 MAC. 우리 기기의 MAC 이 아니면 None (호출측이 4404 로 닫는다).
    서버 설정(Settings validator)과 동일하게 정규화 — 하드웨어가 소문자로 보내도 매칭된다."""
    normalized = normalize_mac(mac)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Device.id).where(Device.mac_address == normalized).limit(1))
        return normalized if result.scalar_one_or_none() is not None else None


async def handle_device_socket(ws: WebSocket, mac: str) -> None:
    await device_manager.connect(mac, ws)
    await _set_connected(mac, True)
    # 넥밴드는 설정을 저장하지 않는다(재부팅하면 기본값) — 붙자마자 현재 값을 알려준다.
    await _send_settings_of_active_user(mac)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("device ws malformed json mac=%s", mac)
                continue
            if isinstance(message, dict) and message.get("type") == "status":
                await _apply_status(mac, message)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("device ws error mac=%s: %s", mac, e)
    finally:
        # 재연결로 교체돼 이미 빠진 연결이면 DB를 건드리지 않는다
        # (새 연결이 True 로 만든 상태를 덮어쓰지 않도록).
        if device_manager.disconnect(mac, ws):
            await _set_connected(mac, False)


async def reset_all_connections() -> None:
    """서버 기동 시 1회: 모든 기기를 미연결로 리셋. WS 는 재시작을 살아남지 못하므로
    부팅 직후 연결된 기기 0대가 항상 진실이다 — 크래시로 남은 stale true 도 함께 정리된다.
    DB 미기동 등으로 실패해도 기동은 계속한다(연결이 들어오면 어차피 다시 True 로 세팅됨)."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(Device).where(Device.is_connected.is_(True)).values(is_connected=False)
            )
            await db.commit()
        if result.rowcount:
            logger.info("startup: reset %s stale device connection(s) to false", result.rowcount)
    except Exception as e:
        logger.warning("startup device connection reset skipped: %s", e)


async def send_vibrate(
    mac: str,
    strength: int,
    sound_name: str,
    sound_category: str,
    direction: Direction = "UNKNOWN",
) -> bool:
    """notification_service 가 매칭 성공 시 호출. 기기 오프라인이면 드롭+로그.
    진동은 실시간 경보라 큐잉하지 않는다 (웹앱 알림·감지 기록은 호출측에서 이미 진행됨)."""
    sent = await device_manager.send_to_device(mac, {
        "type": "vibrate",
        "strength": strength,
        "sound_name": sound_name,
        "sound_category": sound_category,
        "direction": direction,
    })
    if sent:
        logger.info("vibrate sent mac=%s strength=%s sound=%s", mac, strength, sound_name)
    else:
        logger.info("vibrate dropped (device offline) mac=%s sound=%s", mac, sound_name)
    return sent


# 현재 사용자가 없을 때 보내는 값 — 넥밴드 펌웨어의 기본값(settings.cpp)과 같다.
# 이전 사용자의 방해금지·세기가 기기에 남아 다음 사람에게 적용되지 않도록 되돌린다.
DEFAULT_DEVICE_SETTINGS = {
    "emergency_alert_enabled": True,
    "do_not_disturb": False,
    "haptic_strength": 50,
}


def build_settings_message(user: User | None) -> dict:
    """세 값을 항상 모두 담는다 — 넥밴드는 빠진 필드를 현재값으로 두므로, 일부만 보내면
    기기와 서버의 값이 조용히 갈라져도 알 수 없다."""
    if user is None:
        return {"type": "settings_update", **DEFAULT_DEVICE_SETTINGS}
    return {
        "type": "settings_update",
        "emergency_alert_enabled": user.emergency_alert_enabled,
        "do_not_disturb": user.do_not_disturb,
        "haptic_strength": user.haptic_strength,
    }


async def send_settings(mac: str, user: User | None) -> bool:
    """기기 오프라인이면 드롭 — 다시 붙을 때 접속 시 1회 전송이 최신 값을 알려준다."""
    sent = await device_manager.send_to_device(mac, build_settings_message(user))
    logger.info(
        "settings_update %s mac=%s user_id=%s",
        "sent" if sent else "dropped (device offline)", mac, user.id if user else None,
    )
    return sent


async def sync_settings_for_user(db, user: User) -> None:
    """설정을 바꾼 계정이 넥밴드의 현재 사용자일 때만 기기에 알린다.
    아니면 남이 쓰고 있는 넥밴드의 방해금지·세기를 바꿔버린다."""
    result = await db.execute(select(Device.mac_address).where(Device.active_user_id == user.id))
    for mac in result.scalars().all():
        await send_settings(mac, user)


async def _send_settings_of_active_user(mac: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).join(Device, Device.active_user_id == User.id).where(Device.mac_address == mac)
            )
            user = result.scalar_one_or_none()
        await send_settings(mac, user)
    except Exception as e:  # 설정 전송 실패로 기기 연결 자체를 끊지 않는다
        logger.warning("settings_update on connect skipped mac=%s: %s", mac, e)


async def _set_connected(mac: str, connected: bool) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Device)
            .where(Device.mac_address == mac)
            .values(is_connected=connected, last_seen_at=datetime.now(timezone.utc))
        )
        await db.commit()


async def _apply_status(mac: str, message: dict) -> None:
    values: dict = {"last_seen_at": datetime.now(timezone.utc)}
    battery = message.get("battery_level")
    if isinstance(battery, (int, float)) and not isinstance(battery, bool):
        values["battery_level"] = max(0, min(100, int(battery)))
    connection_type = message.get("connection_type")
    if connection_type:
        logger.info("device status mac=%s connection_type=%s", mac, connection_type)
    async with AsyncSessionLocal() as db:
        await db.execute(update(Device).where(Device.mac_address == mac).values(**values))
        await db.commit()
