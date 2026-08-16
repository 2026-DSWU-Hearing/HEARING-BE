"""livesound WS 핸들러. /ws/users/me/detections 와는 완전히 별개의 경로다.

  클라이언트 마이크 → (여기) → AI /ws/analyze → (여기) → 클라이언트

감지 흐름(notification_service)을 **호출하지 않는다**: 알림 저장·FCM·진동·모드 필터·
방해금지 확인이 전부 없다. 사용자가 직접 켠 화면에 지금 들리는 소리를 그대로 비출 뿐이라
넥밴드/모드 상태를 어느 것도 건드리지 않는다.

프로토콜
  C→S  {"type":"start","sample_rate":16000,"channels":1,"format":"pcm_s16le"}
  S→C  {"type":"ready"}
  C→S  바이너리 PCM 조각 (권장 100ms 단위)
  S→C  {"type":"classification","data":{"sounds":[...],"analyzed_at":"..."}}  (반복)
  C→S  {"type":"stop"}  또는 그냥 close
  S→C  {"type":"error","code":"...","message":"..."}
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.logger import logger
from app.db.session import AsyncSessionLocal
from app.schemas.livesound import WINDOW_BYTES, LiveSoundStart
from app.services.livesound_service import (
    AnalyzerClient,
    AnalyzerUnavailable,
    load_sound_id_map,
    to_sound_items,
)

# 분석 대기 슬롯은 1개뿐. AI 가 밀리면 최신 창만 남기고 오래된 건 버린다 —
# 큐가 쌓이면 화면이 몇 초씩 뒤처지고 중지를 눌러도 결과가 계속 올라온다.
_PENDING_WINDOWS = 1


async def handle_livesound_socket(ws: WebSocket, user_id: int) -> None:
    await ws.accept()

    start = await _receive_start(ws)
    if start is None:
        return

    try:
        analyzer = await AnalyzerClient.connect()
    except AnalyzerUnavailable as e:
        logger.warning("livesound: analyzer unavailable user_id=%s: %s", user_id, e)
        await _send_error(ws, "ANALYZER_UNAVAILABLE", "소리 분석 서버에 연결할 수 없습니다.")
        return

    async with AsyncSessionLocal() as db:
        sound_id_by_key = await load_sound_id_map(db)

    await ws.send_json({"type": "ready"})
    logger.info("livesound session started user_id=%s", user_id)

    windows: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_PENDING_WINDOWS)
    tasks = [
        asyncio.create_task(_pump_windows(ws, windows), name="livesound-pump"),
        asyncio.create_task(
            _analyze_windows(ws, windows, analyzer, sound_id_by_key), name="livesound-analyze"
        ),
    ]
    try:
        # 어느 쪽이 먼저 끝나든(클라이언트 종료 / 분석기 두절) 세션 전체를 접는다.
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if isinstance(exc, AnalyzerUnavailable):
                logger.warning("livesound: analyzer lost user_id=%s: %s", user_id, exc)
                await _send_error(ws, "ANALYZER_UNAVAILABLE", "소리 분석이 중단되었습니다.")
            elif exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.error("livesound session error user_id=%s: %s", user_id, exc)
    finally:
        await analyzer.close()
        logger.info("livesound session ended user_id=%s", user_id)


async def _receive_start(ws: WebSocket) -> LiveSoundStart | None:
    """첫 메시지로 오디오 포맷을 선언받는다. 어긋나면 닫는다 — 잘못된 샘플레이트는
    에러 없이 분류 결과만 조용히 망가뜨리므로 여기서 잡아야 한다."""
    try:
        raw = await ws.receive_text()
    except WebSocketDisconnect:
        return None
    except Exception:
        await _send_error(ws, "INVALID_START", "첫 메시지는 start(JSON 텍스트)여야 합니다.")
        return None

    try:
        return LiveSoundStart.model_validate_json(raw)
    except ValidationError as e:
        await _send_error(ws, "INVALID_START", _first_error_message(e))
        return None


async def _pump_windows(ws: WebSocket, windows: asyncio.Queue[bytes]) -> None:
    """클라이언트 PCM 조각을 모아 1초 창으로 잘라 큐에 넣는다."""
    buffer = bytearray()
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return

        text = message.get("text")
        if text is not None:
            if _is_stop(text):
                return
            continue  # start 재전송 등 알 수 없는 텍스트는 무시

        chunk = message.get("bytes")
        if not chunk:
            continue

        buffer.extend(chunk)
        while len(buffer) >= WINDOW_BYTES:
            window = bytes(buffer[:WINDOW_BYTES])
            del buffer[:WINDOW_BYTES]
            _offer_latest(windows, window)


async def _analyze_windows(
    ws: WebSocket,
    windows: asyncio.Queue[bytes],
    analyzer: AnalyzerClient,
    sound_id_by_key: dict[tuple[str, str], int],
) -> None:
    while True:
        window = await windows.get()
        top_sounds = await analyzer.analyze(window)  # AnalyzerUnavailable 은 호출측이 처리
        await ws.send_json(
            {
                "type": "classification",
                "data": {
                    "sounds": to_sound_items(top_sounds, sound_id_by_key),
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        )


def _offer_latest(windows: asyncio.Queue[bytes], window: bytes) -> None:
    """최신 창으로 교체(latest-wins). 큐가 차 있으면 밀린 창을 버린다."""
    if windows.full():
        try:
            windows.get_nowait()
        except asyncio.QueueEmpty:  # 그 사이 분석기가 가져갔으면 그대로 넣으면 된다
            pass
    windows.put_nowait(window)


def _is_stop(raw: str) -> bool:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(message, dict) and message.get("type") == "stop"


def _first_error_message(error: ValidationError) -> str:
    errors = error.errors()
    return errors[0]["msg"] if errors else "start 메시지가 올바르지 않습니다."


async def _send_error(ws: WebSocket, code: str, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "code": code, "message": message})
    except Exception:  # 이미 끊긴 클라이언트 — 알릴 방법이 없다
        pass
