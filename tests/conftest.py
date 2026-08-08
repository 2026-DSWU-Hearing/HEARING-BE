import asyncio
from pathlib import Path

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
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ADMIN_URL = make_url(settings.DATABASE_URL).set(database="postgres")
_TEST_URL = make_url(settings.DATABASE_URL).set(database=TEST_DB_NAME)

# 소리 카탈로그(카테고리 8 + 소리 67)는 마이그레이션이 깔아주는 **레퍼런스 데이터**다.
# 운영에는 항상 존재하므로 테스트에서도 전 구간 상주시킨다 — 테스트별 격리(TRUNCATE)
# 대상에서 빼는 이유. 테스트가 소리를 직접 만들어 쓰면 이름이 코드와 자동으로 맞아떨어져
# '카탈로그에 없는 이름' 류의 버그를 영영 못 잡는다(실제로 그래서 놓친 적 있음).
_CATALOG_TABLES = {"sound_categories", "sounds"}
_ALL_TABLES = ", ".join(
    f'"{t.name}"' for t in Base.metadata.sorted_tables if t.name not in _CATALOG_TABLES
)


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


def _upgrade_test_db_to_head() -> None:
    """테스트 DB 스키마를 `alembic upgrade head` 로 만든다.

    metadata.create_all 이 아니라 마이그레이션을 태우는 이유:
      - 소리 카탈로그 시드가 마이그레이션에 들어 있어 이걸 돌려야 운영과 같은 상태가 된다
      - 스키마 자체도 마이그레이션 결과와 모델 정의가 어긋나면 여기서 드러난다
    alembic env.py 가 settings.DATABASE_URL 을 읽으므로 그동안만 테스트 DB 로 바꿔둔다.
    """
    from alembic import command
    from alembic.config import Config

    original = settings.DATABASE_URL
    settings.DATABASE_URL = _TEST_URL.render_as_string(hide_password=False)
    try:
        cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
        command.upgrade(cfg, "head")
    finally:
        settings.DATABASE_URL = original


async def _teardown_test_db() -> None:
    admin = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await _drop_test_db(conn)
    await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """세션 1회: 전용 PostgreSQL 테스트 DB 생성(+마이그레이션), 종료 시 삭제.
    sync fixture + asyncio.run 으로 자체 루프에서 실행 — 함수 스코프 테스트 루프와 섞이지 않게 한다.
    _upgrade_test_db_to_head 는 alembic env.py 가 자체 asyncio.run 을 돌리므로
    반드시 asyncio.run **밖**(동기 구간)에서 호출해야 한다."""
    try:
        asyncio.run(_setup_test_db())
        _upgrade_test_db_to_head()
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
async def test_session_factory():
    """테스트 DB 를 보는 세션 팩토리 — 요청 스코프 밖에서 자체 세션을 여는 코드
    (기기 WS 핸들러의 AsyncSessionLocal 등)를 monkeypatch 로 바꿔치기할 때 쓴다."""
    engine = create_async_engine(_TEST_URL)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
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
