"""게스트 로그인 남용 방어 — IP별 시간창 카운터 (Redis INCR+EXPIRE).

게스트 로그인은 무인증인데 호출마다 유저+샘플데이터를 만들므로 봇이 DB 를 부풀릴 수 있다.
Redis 다운 시 fail-open: 방어만 꺼지고 로그인은 정상 동작 (가용성 > 방어, 경고 로그).
"""

from app.core.config import settings
from app.core.exceptions import RateLimitException
from app.core.logger import logger
from app.core.redis import get_redis

WINDOW_SECONDS = 3600  # 1시간 고정창


async def check_guest_login_limit(client_ip: str) -> None:
    key = f"rl:guest:{client_ip}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:  # 창의 첫 요청에만 TTL 설정
            await redis.expire(key, WINDOW_SECONDS)
    except Exception as e:
        logger.warning("guest rate limit skipped (redis unavailable): %s", e)
        return
    if count > settings.GUEST_RATE_LIMIT_PER_HOUR:
        raise RateLimitException("Too many guest logins, try again later")
