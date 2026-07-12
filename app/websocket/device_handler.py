"""하드웨어(ESP32) WS 핸들러. /ws/devices?token={device_token}&mac={MAC}

기기 WS 수명주기가 is_connected 의 진실 원천:
  접속 → is_connected=True, 해제 → False (+ last_seen_at 갱신)
  {"type": "status"} 수신 → battery_level·last_seen_at 갱신
  (connection_type 은 FE 미표시라 로그만 남긴다)
진동 명령(send_vibrate)은 notification_service 가 매칭 성공 시 호출한다.
"""

import json
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from app.core.logger import logger
from app.db.session import AsyncSessionLocal
from app.models.device import Device
from app.schemas.device import normalize_mac
from app.websocket.manager import device_manager


async def resolve_device_id(mac: str) -> int | None:
    """접속 MAC → 등록된 Device.id. 미등록이면 None (호출측이 4404 로 닫는다).
    등록 시점(DeviceCreate)과 동일하게 정규화 — 하드웨어가 소문자로 보내도 매칭된다."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Device.id).where(Device.mac_address == normalize_mac(mac)))
        return result.scalar_one_or_none()


async def handle_device_socket(ws: WebSocket, device_id: int) -> None:
    await device_manager.connect(device_id, ws)
    await _set_connected(device_id, True)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("device ws malformed json device_id=%s", device_id)
                continue
            if isinstance(message, dict) and message.get("type") == "status":
                await _apply_status(device_id, message)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("device ws error device_id=%s: %s", device_id, e)
    finally:
        # 재연결로 교체됐거나 close_device()로 이미 빠진 연결이면 DB를 건드리지 않는다
        # (새 연결이 True 로 만든 상태 / PATCH 가 False 로 만든 상태를 덮어쓰지 않도록).
        if device_manager.disconnect(device_id, ws):
            await _set_connected(device_id, False)


async def send_vibrate(device_id: int, strength: int, sound_name: str, sound_category: str) -> bool:
    """notification_service 가 매칭 성공 시 호출. 기기 오프라인이면 드롭+로그.
    진동은 실시간 경보라 큐잉하지 않는다 (웹앱 알림·감지 기록은 호출측에서 이미 진행됨)."""
    sent = await device_manager.send_to_device(device_id, {
        "type": "vibrate",
        "strength": strength,
        "sound_name": sound_name,
        "sound_category": sound_category,
    })
    if sent:
        logger.info("vibrate sent device_id=%s strength=%s sound=%s", device_id, strength, sound_name)
    else:
        logger.info("vibrate dropped (device offline) device_id=%s sound=%s", device_id, sound_name)
    return sent


async def _set_connected(device_id: int, connected: bool) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Device)
            .where(Device.id == device_id)
            .values(is_connected=connected, last_seen_at=datetime.now(timezone.utc))
        )
        await db.commit()


async def _apply_status(device_id: int, message: dict) -> None:
    values: dict = {"last_seen_at": datetime.now(timezone.utc)}
    battery = message.get("battery_level")
    if isinstance(battery, (int, float)) and not isinstance(battery, bool):
        values["battery_level"] = max(0, min(100, int(battery)))
    connection_type = message.get("connection_type")
    if connection_type:
        logger.info("device status device_id=%s connection_type=%s", device_id, connection_type)
    async with AsyncSessionLocal() as db:
        await db.execute(update(Device).where(Device.id == device_id).values(**values))
        await db.commit()
