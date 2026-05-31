"""로컬 개발 부트스트랩: 테이블 생성 + 개발 유저 + 사운드 카탈로그 시드.

로그인/마이그레이션을 붙이기 전, 흐름 A(소리감지→모드 필터→알림)를 바로 돌려보기 위한 용도다.
- 테이블은 alembic 대신 `create_all`로 즉석 생성한다(운영 마이그레이션은 alembic 사용).
- 시드 소리 목록은 AI팀 분류 확정 전 임시값.

사용:
  docker compose up -d postgres   # 또는 다른 PostgreSQL 기동
  python -m app.devinit
"""

import asyncio

from sqlalchemy import select

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine

# 모든 모델을 Base.metadata 에 등록 (create_all 대상이 되도록)
from app.models import device, mode, notification, sound, user  # noqa: F401
from app.models.sound import Sound, SoundCategory
from app.models.user import User

DEV_USER_ID = 1

# (카테고리, [(소리이름, 위험도)]) — AI팀 분류 확정 전 임시 시드
SEED_CATALOG: dict[str, list[tuple[str, str]]] = {
    "위험": [("화재경보기", "HIGH"), ("자동차 경적", "HIGH"), ("사이렌", "HIGH")],
    "생활": [("초인종", "MEDIUM"), ("노크", "LOW"), ("전자레인지 알림", "LOW")],
    "사람": [("이름 부르기", "MEDIUM"), ("아기 울음", "HIGH")],
}


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


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await ensure_dev_user(db)
        await seed_sounds(db)

    token = create_access_token(DEV_USER_ID, source="user")
    print("DB 준비 완료. dev user_id =", DEV_USER_ID)
    print(f"Authorization: Bearer {token}")


if __name__ == "__main__":
    asyncio.run(main())
