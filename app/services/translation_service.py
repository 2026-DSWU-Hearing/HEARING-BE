"""번역 서비스 (외국인 대화 시). DeepL / 파파고 API 호출 예정."""

import httpx

from app.core.logger import logger


async def translate(text: str, source_lang: str, target_lang: str) -> str:
    """기본은 입력 그대로 반환. 외부 API 키 설정 후 구현."""
    raise NotImplementedError
