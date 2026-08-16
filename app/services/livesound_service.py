"""livesound 서비스 — AI 분석 서버(HEARING-MODEL) 왕복과 응답 변환.

이 경로는 DB 를 쓰기 목적으로 건드리지 않는다. 소리 카탈로그를 세션 시작 시 한 번 읽어
이름→sound_id 를 붙여줄 뿐이다(FE 목록 key, 후속 '모드에 추가' 여지).
"""

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.models.sound import Sound, SoundCategory
from app.schemas.livesound import SoundItem


class AnalyzerUnavailable(Exception):
    """AI 서버에 붙지 못했거나 세션 도중 끊겼다. 호출측이 error 메시지로 변환한다."""


class AnalyzerClient:
    """AI 서버의 분석 전용 WS(/ws/analyze) 클라이언트.

    프로토콜: PCM 바이너리 1프레임 전송 → JSON 1건 수신(요청-응답 1:1).
    기존 ESP32용 /ws 와 달리 방향 4바이트 헤더를 붙이지 않는다(브라우저엔 방향이 없다).
    """

    def __init__(self, ws) -> None:
        self._ws = ws

    @classmethod
    async def connect(cls) -> "AnalyzerClient":
        from websockets.asyncio.client import connect as ws_connect

        url = settings.AI_SERVER_WS_URL
        if not url:
            raise AnalyzerUnavailable("AI_SERVER_WS_URL is not configured")
        try:
            ws = await asyncio.wait_for(
                ws_connect(url), timeout=settings.AI_CONNECT_TIMEOUT_SECONDS
            )
        except Exception as e:
            raise AnalyzerUnavailable(f"cannot reach analyzer at {url}: {e}") from e
        return cls(ws)

    async def analyze(self, pcm: bytes) -> list[dict]:
        """1초 PCM → top_sounds. AI 가 준 원본 형태(category/block/score)를 그대로 넘긴다."""
        try:
            await self._ws.send(pcm)
            raw = await asyncio.wait_for(
                self._ws.recv(), timeout=settings.AI_ANALYZE_TIMEOUT_SECONDS
            )
        except Exception as e:
            raise AnalyzerUnavailable(f"analyzer round-trip failed: {e}") from e

        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as e:
            raise AnalyzerUnavailable(f"analyzer sent non-JSON: {e}") from e

        # dict 가 아니면 아래 .get 이 AttributeError 로 터지는데, 그건 AnalyzerUnavailable 이
        # 아니라서 호출측이 FE 에 아무 안내도 못 보내고 소켓만 닫힌다(원인 없는 침묵).
        if not isinstance(payload, dict):
            raise AnalyzerUnavailable(f"analyzer sent non-object: {type(payload).__name__}")

        # status 를 반드시 본다. 분석 실패도 top_sounds 를 [] 로 함께 보내기 때문에,
        # 이걸 안 보면 '분석 실패' 와 '조용해서 잡힌 게 없음' 이 화면에서 똑같아진다.
        #
        # 실패면 세션을 접는다. AI 가 error 를 내는 경우는 프레임 크기 불일치 하나뿐인데,
        # _pump_windows 가 항상 정확히 WINDOW_BYTES 로 잘라 보내므로 **구조적으로 날 수 없다**
        # → 나면 백엔드 버그다. 그 상태로 계속하면 매초 같은 실패를 반복하면서 화면은 빈 채로
        # 남으므로, 조용히 비어 있느니 한 번 크게 실패하는 편이 낫다.
        # (요청-응답 1:1 이라 에러 응답을 받아도 스트림이 어긋나진 않는다 — 끊는 건 판단이지 제약이 아니다.)
        status = payload.get("status")
        if status != "ok":
            message = payload.get("message")
            detail = message if isinstance(message, str) else f"status={status!r}"
            raise AnalyzerUnavailable(f"analyzer returned error: {detail}")

        top_sounds = payload.get("top_sounds")
        if not isinstance(top_sounds, list):
            raise AnalyzerUnavailable(f"analyzer sent invalid top_sounds: {type(top_sounds).__name__}")
        return top_sounds

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:  # 이미 끊긴 소켓 — 정리 실패는 무시
            pass


async def load_sound_id_map(db: AsyncSession) -> dict[tuple[str, str], int]:
    """(카테고리, 이름) → sound_id. 세션당 1회만 읽는다(카탈로그는 61행짜리 레퍼런스 데이터).

    이름만으로 담으면 안 된다 — '충돌·파손음' 은 긴급/생활음 두 카테고리에 각각 존재해서
    나중 행이 앞 행을 덮어쓰고, 긴급으로 잡힌 소리에 생활음 id 가 붙는다.
    감지 흐름(notification_service._resolve_sound_id)도 같은 이유로 카테고리까지 함께 본다.
    """
    rows = await db.execute(
        select(Sound.id, Sound.name, SoundCategory.name).join(
            SoundCategory, Sound.category_id == SoundCategory.id
        )
    )
    return {(category, name): sound_id for sound_id, name, category in rows.all()}


def to_sound_items(
    top_sounds: list[dict], sound_id_by_key: dict[tuple[str, str], int]
) -> list[dict]:
    """AI 응답(category/block/score) → 화면용(sound_name/sound_category/confidence).

    임계값 컷을 하지 않는다 — livesound 는 '지금 들리는 것 전부'를 보여주는 화면이고,
    무엇을 알릴지 고르는 판단은 감지 흐름(notification_service) 쪽 책임이다.
    """
    items: list[dict] = []
    for entry in top_sounds:
        if not isinstance(entry, dict):
            continue
        sound_name = entry.get("block")
        sound_category = entry.get("category") or ""
        score = entry.get("score")
        if not sound_name or not isinstance(score, (int, float)) or isinstance(score, bool):
            logger.warning("livesound: dropping malformed analyzer entry: %s", entry)
            continue
        items.append(
            SoundItem(
                sound_id=sound_id_by_key.get((sound_category, sound_name)),
                sound_name=sound_name,
                sound_category=sound_category,
                confidence=float(score),
            ).model_dump()
        )
    return items
