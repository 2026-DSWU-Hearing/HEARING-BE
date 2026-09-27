"""RTZR(VITO) 실시간 STT 클라이언트 — 토큰 발급/캐시와 스트리밍 소켓.

이 모듈은 DB 를 모른다. 대화 소유 확인·클라이언트 소켓 수명은 websocket/stt_handler 가 맡고,
여기는 '상류(RTZR)와 어떻게 말하는가'만 안다.

RTZR 스트리밍 프로토콜(https://developers.rtzr.ai/docs/stt-streaming/):
  접속   wss://openapi.vito.ai/v1/transcribe:streaming?sample_rate=16000&encoding=LINEAR16&...
         Authorization: Bearer <access_token>  (그래서 브라우저가 직접 못 붙는다 — 헤더 불가)
  C→S    바이너리 PCM 조각, 마지막에 텍스트 "EOS"
  S→C    {"seq":n,"start_at":ms,"duration":ms,"final":bool,"alternatives":[{"text":"..."}]}
         EOS 이후 남은 final 을 흘려보내고 서버가 닫는다.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.logger import logger

# 문서 계약(FE sttConfig/useSttSocket 과 합의): 16kHz mono PCM int16, 한국어 모델, 숫자 정규화·간투어 제거.
STREAM_QUERY = {
    "sample_rate": "16000",
    "encoding": "LINEAR16",
    "model_name": "sommers_ko",
    "use_itn": "true",
    "use_disfluency_filter": "true",
}
EOS = "EOS"

# 만료 직전 토큰으로 접속했다가 401 을 맞지 않도록 두는 여유.
TOKEN_EXPIRY_MARGIN_SECONDS = 60


class SttUnavailable(Exception):
    """RTZR 에 붙지 못했거나(자격·네트워크) 세션 도중 비정상 종료. 호출측이 close 코드로 변환한다."""


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # unix seconds


# 프로세스 내 캐시. RTZR 토큰은 수 시간짜리라 세션마다 발급하면 낭비이고 발급 API 에도 한도가 있다.
# 동시 세션이 만료 시점에 겹쳐도 한 번만 발급하도록 락을 건다.
_token: _CachedToken | None = None
_token_lock = asyncio.Lock()


def _is_usable(token: _CachedToken | None) -> bool:
    return token is not None and token.expires_at - TOKEN_EXPIRY_MARGIN_SECONDS > time.time()


def invalidate_token() -> None:
    """접속이 401 로 거부되는 등 토큰이 의심되면 버린다 — 다음 세션이 새로 발급받는다."""
    global _token
    _token = None


async def get_access_token() -> str:
    global _token
    if _is_usable(_token):
        return _token.access_token
    async with _token_lock:
        if _is_usable(_token):  # 락 기다리는 사이 다른 세션이 발급했으면 그걸 쓴다
            return _token.access_token
        _token = await _issue_token()
        return _token.access_token


async def _issue_token() -> _CachedToken:
    if not settings.RTZR_CLIENT_ID or not settings.RTZR_CLIENT_SECRET:
        raise SttUnavailable("RTZR_CLIENT_ID / RTZR_CLIENT_SECRET is not configured")
    try:
        async with httpx.AsyncClient(timeout=settings.RTZR_CONNECT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.RTZR_API_BASE.rstrip('/')}/v1/authenticate",
                data={
                    "client_id": settings.RTZR_CLIENT_ID,
                    "client_secret": settings.RTZR_CLIENT_SECRET,
                },
            )
            response.raise_for_status()
            payload = response.json()
        return _CachedToken(access_token=payload["access_token"], expires_at=float(payload["expire_at"]))
    except Exception as e:
        raise SttUnavailable(f"RTZR token issue failed: {e}") from e


def stream_url() -> str:
    base = settings.RTZR_API_BASE.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return f"{base}/v1/transcribe:streaming?{urlencode(STREAM_QUERY)}"


class SttStreamClient:
    """RTZR 스트리밍 소켓 하나 = 대화 한 번의 마이크 세션 하나."""

    def __init__(self, ws) -> None:
        self._ws = ws

    @classmethod
    async def connect(cls) -> "SttStreamClient":
        from websockets.asyncio.client import connect as ws_connect

        token = await get_access_token()
        url = stream_url()
        try:
            ws = await asyncio.wait_for(
                ws_connect(url, additional_headers={"Authorization": f"Bearer {token}"}),
                timeout=settings.RTZR_CONNECT_TIMEOUT_SECONDS,
            )
        except Exception as e:
            # 원인이 토큰(401)이든 네트워크든 구분하지 않고 캐시를 버린다 — 재발급 비용은 작고,
            # 만료·폐기된 토큰을 붙들고 계속 실패하는 쪽이 훨씬 비싸다.
            invalidate_token()
            raise SttUnavailable(f"cannot reach RTZR at {url}: {e}") from e
        return cls(ws)

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self._ws.send(pcm)
        except Exception as e:
            raise SttUnavailable(f"RTZR send failed: {e}") from e

    async def send_eos(self) -> None:
        try:
            await self._ws.send(EOS)
        except Exception as e:
            raise SttUnavailable(f"RTZR EOS failed: {e}") from e

    async def recv(self) -> dict | None:
        """다음 인식 결과. RTZR 이 정상 종료(EOS 처리 완료)하면 None."""
        from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

        try:
            raw = await self._ws.recv()
        except ConnectionClosedOK:
            return None
        except ConnectionClosedError as e:
            # 1000 이 아닌 코드로 닫힘. RTZR 이 세션 한도·오디오 형식 문제로 끊는 경우가 여기 온다.
            raise SttUnavailable(f"RTZR closed abnormally: {e}") from e
        except Exception as e:
            raise SttUnavailable(f"RTZR recv failed: {e}") from e
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as e:
            raise SttUnavailable(f"RTZR sent non-JSON: {e}") from e
        if not isinstance(payload, dict):
            raise SttUnavailable(f"RTZR sent non-object: {type(payload).__name__}")
        return payload

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:  # 이미 끊긴 소켓 — 정리 실패는 무시
            pass


def to_client_message(payload: dict) -> dict | None:
    """RTZR {final, alternatives:[{text}]} → FE {content, isFinal}. 텍스트가 없으면 None(보내지 않음).

    FE(useSttSocket)는 content 가 비면 무시하고, isFinal 이면 버블로 확정한다. 빈 final 을 굳이
    내려보내면 FE 가 아무것도 안 하니 여기서 거른다."""
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        return None
    first = alternatives[0]
    text = first.get("text") if isinstance(first, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    return {"content": text.strip(), "isFinal": bool(payload.get("final"))}
