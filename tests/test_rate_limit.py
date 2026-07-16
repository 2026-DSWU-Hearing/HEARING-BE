"""게스트 로그인 rate limit — 실 Redis(테스트 DB 15) + 실제 엔드포인트로 검증."""

import pytest

from app.core import rate_limit
from app.core.config import settings


@pytest.mark.asyncio
async def test_guest_login_429_after_limit(api_client, test_redis, monkeypatch):
    client, _ = api_client
    monkeypatch.setattr(settings, "GUEST_RATE_LIMIT_PER_HOUR", 3)

    for _ in range(3):
        r = await client.post("/auth/guest")
        assert r.status_code == 200, r.text

    r = await client.post("/auth/guest")
    assert r.status_code == 429, r.text
    assert r.json()["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_guest_login_fail_open_when_redis_down(api_client, monkeypatch):
    """Redis 가 죽어도 게스트 로그인은 정상 — 방어(가산·차단)만 건너뛴다."""
    client, _ = api_client

    class DeadRedis:
        def __getattr__(self, name):
            async def _fail(*args, **kwargs):
                raise ConnectionError("redis down")
            return _fail

    monkeypatch.setattr(rate_limit, "get_redis", lambda: DeadRedis())

    r = await client.post("/auth/guest")
    assert r.status_code == 200, r.text
