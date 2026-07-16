import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis as redis_core
from app.core.config import settings
from app.db.base import Base
from app.db.dependencies import get_db
from app.main import app
from app.models import device, mode, notification, sound, user  # noqa: F401  (메타데이터 등록)

# 서비스 유닛테스트는 인메모리 SQLite 가 아니라 **실제 PostgreSQL** 로 돈다
# (타입·제약·시퀀스·flush 동작이 운영과 동일해야 헛된 통과를 막는다).
# 운영/개발 DB(`hearing`)를 건드리지 않도록 전용 테스트 DB 를 만들고 끝나면 삭제한다.
TEST_DB_NAME = "hearing_test"
_ADMIN_URL = make_url(settings.DATABASE_URL).set(database="postgres")
_TEST_URL = make_url(settings.DATABASE_URL).set(database=TEST_DB_NAME)
_ALL_TABLES = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _drop_test_db(conn) -> None:
    # 다른 연결이 물고 있으면 DROP 이 막히므로 먼저 종료시킨다.
    await conn.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
    )
    await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))


async def _setup_test_db() -> None:
    admin = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:  # CREATE DATABASE 는 트랜잭션 밖(AUTOCOMMIT)에서만 가능
        await _drop_test_db(conn)
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    await admin.dispose()

    engine = create_async_engine(_TEST_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _teardown_test_db() -> None:
    admin = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await _drop_test_db(conn)
    await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """세션 1회: 전용 PostgreSQL 테스트 DB 생성(+스키마), 종료 시 삭제.
    sync fixture + asyncio.run 으로 자체 루프에서 실행 — 함수 스코프 테스트 루프와 섞이지 않게 한다."""
    try:
        asyncio.run(_setup_test_db())
    except Exception as exc:  # Postgres 미기동 등 — 원인을 분명히 보여준다
        pytest.skip(f"PostgreSQL 테스트 DB 준비 실패 (docker compose up -d postgres 필요?): {exc}")
    yield
    asyncio.run(_teardown_test_db())


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """테스트별 세션(실 PostgreSQL). 각 테스트 후 전 테이블 TRUNCATE 로 격리한다(시퀀스도 리셋).
    함수 스코프 엔진이라 pytest-asyncio 의 함수 루프와 커넥션이 어긋나지 않는다."""
    engine = create_async_engine(_TEST_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def test_redis(monkeypatch):
    """실 Redis, 테스트 전용 DB 15 — dev(/0)와 키공간 분리, 테스트 후 flush.
    get_redis() 싱글턴을 이 클라이언트로 바꿔치기한다(rate limit·블랙리스트가 여길 보게).
    Redis 미기동이면 skip."""
    from redis.asyncio import from_url

    base = settings.REDIS_URL.rsplit("/", 1)[0]
    client = from_url(f"{base}/15", decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Redis 필요 (docker compose up -d redis): {exc}")
    monkeypatch.setattr(redis_core, "_client", client)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def api_client():
    """앱(FastAPI)을 테스트 DB 에 물린 ASGI 클라이언트 — 흐름 A 같은 엔드투엔드 통합테스트용.
    (스모크 스크립트가 standalone 으로 하던 흐름을 pytest 안에서 실 Postgres 로 돌린다.)
    `get_db` 를 테스트 세션으로 오버라이드하고, 요청마다 새 세션을 준다(운영과 동일).
    반환: (client, session_factory) — session_factory 로 시드 데이터를 넣는다."""
    engine = create_async_engine(_TEST_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
        await engine.dispose()
