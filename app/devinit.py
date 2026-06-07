"""로컬 개발 부트스트랩: 마이그레이션(alembic) + 개발 유저 + 사운드 카탈로그 시드.

로그인을 붙이기 전, 흐름 A(소리감지→모드 필터→알림)를 바로 돌려보기 위한 용도다.
- 스키마는 **alembic 마이그레이션**으로 만든다(`alembic upgrade head`). create_all 아님 —
  alembic 이 스키마 단일 출처이므로 새 DB도 자동으로 베이스라인이 stamp 된다.
- 시드 소리 목록은 AI팀 분류 확정 전 임시값.

사용(백엔드 루트에서 실행):
  docker compose up -d postgres   # 또는 다른 PostgreSQL 기동
  python -m app.devinit
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal

# 모든 모델을 레지스트리에 등록(관계 문자열 해석 + 매퍼 구성용)
from app.models import device, mode, notification, sound, user  # noqa: F401
from app.models.sound import Sound, SoundCategory
from app.models.user import User

BASE_DIR = Path(__file__).resolve().parent.parent  # 백엔드 루트(alembic.ini 위치)
DEV_USER_ID = 1

# (카테고리, [(소리이름, 위험도)]) — AI팀 분류 확정 전 임시 시드
SEED_CATALOG: dict[str, list[tuple[str, str]]] = {
    "위험": [("화재경보기", "HIGH"), ("자동차 경적", "HIGH"), ("사이렌", "HIGH")],
    "생활": [("초인종", "MEDIUM"), ("노크", "LOW"), ("전자레인지 알림", "LOW")],
    "사람": [("이름 부르기", "MEDIUM"), ("아기 울음", "HIGH")],
}


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


async def seed_sounds(db) -> None:
    if await db.scalar(select(Sound.id).limit(1)):
        return
    for category_name, sounds in SEED_CATALOG.items():
        category = SoundCategory(name=category_name)
        db.add(category)
        await db.flush()
        for name, risk in sounds:
            db.add(Sound(name=name, category_id=category.id, risk_level=risk))
    await db.commit()


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        await ensure_dev_user(db)
        await seed_sounds(db)


def main() -> None:
    run_migrations()      # 스키마: alembic upgrade head (동기)
    asyncio.run(seed())   # 데이터 시드 (비동기)

    token = create_access_token(DEV_USER_ID, source="user")
    print("DB 준비 완료 (alembic upgrade head). dev user_id =", DEV_USER_ID)
    print(f"Authorization: Bearer {token}")


if __name__ == "__main__":
    main()
