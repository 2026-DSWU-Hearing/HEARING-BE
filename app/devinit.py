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
from sqlalchemy import delete, select

from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal

# 모든 모델을 레지스트리에 등록(관계 문자열 해석 + 매퍼 구성용)
from app.models import device, mode, notification, sound, user  # noqa: F401
from app.models.sound import Sound, SoundCategory
from app.models.user import User

BASE_DIR = Path(__file__).resolve().parent.parent  # 백엔드 루트(alembic.ini 위치)
DEV_USER_ID = 1

# (카테고리, [(소리이름, 위험도)])
SEED_CATALOG: dict[str, list[tuple[str, str]]] = {
    "긴급": [("화재 경보", "HIGH"), ("사이렌", "HIGH"), ("경보음", "HIGH"), ("응급차량", "HIGH"), ("폭발·파열음", "HIGH"), ("충돌·파손음", "HIGH")],
    "교통": [("자동차 경고음", "MEDIUM"), ("급정거·마찰음", "LOW"), ("경적", "LOW"), ("기차", "LOW"), ("차량 주행음", "LOW"), ("오토바이", "LOW"), ("항공기", "LOW"), ("엔진", "LOW"), ("기타 이동수단", "LOW")],
    "사람": [("비명", "MEDIUM"), ("울음", "HIGH"), ("호흡·기침", "LOW"), ("신음", "LOW"), ("음성", "LOW"), ("아기 옹알이", "LOW"), ("웃음", "LOW"), ("노래", "LOW"), ("군중", "LOW"), ("발걸음", "LOW")],
    "생활음": [("가전제품", "MEDIUM"), ("욕실 물 소리", "HIGH"), ("물 튀는 소리", "LOW"), ("스프레이", "LOW"), ("사무기기", "LOW"), ("클릭음", "LOW"), ("휙 소리", "LOW"), ("바스락", "LOW"), ("전자 알림음", "LOW"), ("문 닫힘 소리", "LOW"),
            ("노크 소리", "MEDIUM"), ("열쇠 소리", "MEDIUM"), ("충돌·파손음", "MEDIUM"), ("공구", "MEDIUM"), ("실내 배경음", "MEDIUM"), ("타격음", "MEDIUM"), ("마찰음", "MEDIUM"), ("소음", "MEDIUM"), ("냉난방·기계음", "MEDIUM"), ("증기", "MEDIUM") ],
    "자연": [("바람·비", "MEDIUM"), ("천둥", "HIGH"), ("나뭇잎 소리", "LOW"), ("화산 분출음", "LOW"), ("물가", "LOW")],
    "동물": [("고양이", "MEDIUM"), ("개", "HIGH"), ("새", "LOW"), ("가축", "LOW"), ("뱀", "LOW"), ("벌레", "LOW"), ("맹수·야생동물", "LOW")],
    "주방": [("끓는 소리", "MEDIUM"), ("식기", "HIGH"), ("주방 도구", "LOW"), ("조리", "LOW")],
    "음악": [("대중 음악", "MEDIUM"), ("피아노", "HIGH"), ("현악기", "LOW"), ("드럼", "LOW"), ("재즈", "LOW"), ("클래식", "LOW")]
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
    """SEED_CATALOG 를 카테고리/소리 테이블에 동기화.

    카탈로그를 편집하고 `python -m app.devinit` 를 다시 돌리면 반영된다.
    내용이 이미 동일하면 그대로 둬서 모드의 소리 선택(mode_sounds)을 보존하고,
    달라졌을 때만 전체 재구성한다(소리 삭제 시 mode_sounds 는 ON DELETE CASCADE 로 정리됨).
    """
    desired = {
        (category_name, name, risk)
        for category_name, sounds in SEED_CATALOG.items()
        for name, risk in sounds
    }
    rows = await db.execute(
        select(SoundCategory.name, Sound.name, Sound.risk_level).join(
            Sound, Sound.category_id == SoundCategory.id
        )
    )
    if {tuple(r) for r in rows.all()} == desired:
        return

    await db.execute(delete(Sound))
    await db.execute(delete(SoundCategory))
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
