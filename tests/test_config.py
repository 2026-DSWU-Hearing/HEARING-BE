import pytest
from pydantic import ValidationError

from app.core.config import Settings

# _env_file=None: 로컬 .env 를 읽지 않는 완전 격리 — 필수값은 직접 넘긴다.
BASE = dict(
    _env_file=None,
    DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
    JWT_SECRET="x" * 40,
)


def test_prod_rejects_auth_bypass():
    with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS"):
        Settings(**BASE, ENVIRONMENT="prod", DEV_AUTH_BYPASS=True)


def test_prod_without_bypass_boots():
    settings = Settings(**BASE, ENVIRONMENT="prod", DEV_AUTH_BYPASS=False)

    assert settings.ENVIRONMENT == "prod"


def test_dev_allows_bypass():
    settings = Settings(**BASE, ENVIRONMENT="dev", DEV_AUTH_BYPASS=True)

    assert settings.DEV_AUTH_BYPASS is True


def test_unknown_environment_rejected():
    # Literal 검증 — "production" 같은 오타로 가드가 조용히 무력화되는 것을 막는다
    with pytest.raises(ValidationError):
        Settings(**BASE, ENVIRONMENT="production")
