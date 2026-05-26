"""GPS 좌표 → 역지오코딩 (시/구 단위 텍스트). 카카오 로컬 API 사용."""

import httpx

from app.core.config import settings
from app.core.logger import logger


async def reverse_geocode(latitude: float, longitude: float) -> str | None:
    if not settings.KAKAO_REST_API_KEY:
        return None
    url = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
    headers = {"Authorization": f"KakaoAK {settings.KAKAO_REST_API_KEY}"}
    params = {"x": longitude, "y": latitude}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
            docs = data.get("documents", [])
            if not docs:
                return None
            doc = docs[0]
            return f"{doc.get('region_1depth_name', '')} {doc.get('region_2depth_name', '')}".strip()
    except Exception as e:
        logger.warning("reverse_geocode failed: %s", e)
        return None
