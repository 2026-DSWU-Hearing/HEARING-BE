"""Redis 연결 (인메모리-임시 저장소). PostgreSQL(관계형-영구)과 역할을 나눈다.

용도:
  - 게스트 로그인 rate limit (core/rate_limit.py) — IP별 카운터+TTL
  - 로그아웃된 refresh 토큰 블랙리스트 (services/auth_service.py) — TTL=토큰 잔여수명

장애 정책은 fail-open: Redis 가 죽어도 로그인/재발급/로그아웃 자체는 동작하고
방어 기능만 꺼진다(각 사용처에서 경고 로그). 데이터가 전부 TTL 임시라 영속화도 하지 않는다.
"""

from redis.asyncio import Redis, from_url

from app.core.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    """지연 초기화 싱글턴 (push_service 의 FCM lazy init 과 같은 패턴)."""
    global _client
    if _client is None:
        _client = from_url(settings.REDIS_URL, decode_responses=True)
    return _client
