"""RTZR VITO Speech API 호출 (한국어 STT, CER 5.91%)."""

import httpx

from app.core.config import settings
from app.core.logger import logger

_token_cache: dict[str, str] = {}


async def _get_access_token() -> str:
    if "token" in _token_cache:
        return _token_cache["token"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{settings.RTZR_API_BASE}/v1/authenticate",
            data={
                "client_id": settings.RTZR_CLIENT_ID,
                "client_secret": settings.RTZR_CLIENT_SECRET,
            },
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        _token_cache["token"] = token
        return token


async def transcribe_audio(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """오디오 바이트 → 한국어 텍스트. (실시간 스트리밍은 RTZR WebSocket API로 별도 구현)"""
    try:
        token = await _get_access_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{settings.RTZR_API_BASE}/v1/transcribe",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("audio.wav", audio_bytes, "audio/wav")},
                data={"config": '{"use_diarization": false}'},
            )
            r.raise_for_status()
            return r.json().get("text", "")
    except Exception as e:
        logger.error("STT failed: %s", e)
        return ""
