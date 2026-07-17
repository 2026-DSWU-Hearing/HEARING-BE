"""로컬 개발 부트스트랩: 마이그레이션(alembic) + 개발 유저/디바이스 시드.

로그인을 붙이기 전, 흐름 A(소리감지→모드 필터→알림)를 바로 돌려보기 위한 용도다.
- 스키마 + 소리 카탈로그는 **alembic 마이그레이션**으로 만든다(`alembic upgrade head`).
  소리 카탈로그(레퍼런스 데이터)는 데이터 마이그레이션(seed_sound_catalog)이 넣으므로
  여기서 따로 시드하지 않는다 — 카탈로그 변경은 새 마이그레이션으로.
- 테스트용 디바이스 1개를 고정 id로 시드 → AI서버/스크립트가 등록 절차 없이 바로 감지 POST 가능.

사용(백엔드 루트에서 실행):
  docker compose up -d postgres   # 또는 다른 PostgreSQL 기동
  python -m app.devinit
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal

# 모든 모델을 레지스트리에 등록(관계 문자열 해석 + 매퍼 구성용)
from app.models import device, mode, notification, sound, user  # noqa: F401
from app.models.device import Device
from app.models.user import User

BASE_DIR = Path(__file__).resolve().parent.parent  # 백엔드 루트(alembic.ini 위치)
DEV_USER_ID = 1
DEV_DEVICE_ID = 1


def run_migrations() -> None:
    """`alembic upgrade head`. env.py 가 내부에서 asyncio.run 을 돌리므로 반드시 동기 컨텍스트에서 호출."""
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    command.upgrade(cfg, "head")


async def ensure_dev_user(db) -> None:
    if await db.get(User, DEV_USER_ID):
        return
    db.add(User(id=DEV_USER_ID, email="dev@hearing.local", nickname="dev", terms_agreed=True))
    await db.commit()


async def ensure_dev_device(db) -> None:
    """테스트용 디바이스 1개. AI서버/스크립트가 POST /devices/{id}/detections 를
    별도 등록·페어링 절차 없이 고정 id로 바로 쏠 수 있게 시드한다(로그인 우회와 같은 취지).
    MAC 은 실기기와 동일(공유 MAC) — is_connected 는 기기 WS 접속만이 켤 수 있으므로 시드하지 않는다."""
    if await db.get(Device, DEV_DEVICE_ID):
        return
    db.add(Device(
        id=DEV_DEVICE_ID,
        user_id=DEV_USER_ID,
        nickname="개발용 디바이스",
        mac_address=settings.DEVICE_MAC_ADDRESS,
    ))
    await db.commit()


async def reset_sequences(db) -> None:
    """명시적 id(dev user=1, dev device=1)로 시드하면 Postgres 시퀀스가 안 올라가서,
    이후 자동 id INSERT(게스트·구글 로그인 등 새 유저/디바이스 생성)가 id=1 로 충돌한다.
    → 시드한 테이블의 시퀀스를 현재 MAX(id) 에 맞춰 다음 INSERT 가 MAX+1 을 쓰게 한다."""
    for table in ("users", "devices"):
        await db.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM {table}))"
            )
        )
    await db.commit()


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        await ensure_dev_user(db)
        await ensure_dev_device(db)
        await reset_sequences(db)


def main() -> None:
    run_migrations()      # 스키마: alembic upgrade head (동기)
    asyncio.run(seed())   # 데이터 시드 (비동기)

    user_token = create_access_token(DEV_USER_ID, source="user")
    ai_token = create_access_token(DEV_USER_ID, source="ai-server")
    print("DB 준비 완료 (alembic upgrade head). dev user_id =", DEV_USER_ID)
    print(f"dev device_id = {DEV_DEVICE_ID}  →  POST /devices/{DEV_DEVICE_ID}/detections")
    print(f"앱 API 토큰      : Bearer {user_token}")
    print(f"AI서버 감지 토큰 : Bearer {ai_token}")


if __name__ == "__main__":
    main()
