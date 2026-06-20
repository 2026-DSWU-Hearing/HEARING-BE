"""로컬 개발 부트스트랩: 마이그레이션(alembic) + 개발 유저/디바이스 + 사운드 카탈로그 시드.

로그인을 붙이기 전, 흐름 A(소리감지→모드 필터→알림)를 바로 돌려보기 위한 용도다.
- 스키마는 **alembic 마이그레이션**으로 만든다(`alembic upgrade head`). create_all 아님 —
  alembic 이 스키마 단일 출처이므로 새 DB도 자동으로 베이스라인이 stamp 된다.
- 시드 소리 이름은 AI팀 분류(category_map.py)의 한글 이름과 일치시켜 둠 → 이름기반 매칭이 됨.
- 테스트용 디바이스 1개를 고정 id로 시드 → AI서버/스크립트가 등록 절차 없이 바로 감지 POST 가능.

사용(백엔드 루트에서 실행):
  docker compose up -d postgres   # 또는 다른 PostgreSQL 기동
  python -m app.devinit
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text

from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal

# 모든 모델을 레지스트리에 등록(관계 문자열 해석 + 매퍼 구성용)
from app.models import device, mode, notification, sound, user  # noqa: F401
from app.models.device import Device
from app.models.sound import Sound, SoundCategory
from app.models.user import User

BASE_DIR = Path(__file__).resolve().parent.parent  # 백엔드 루트(alembic.ini 위치)
DEV_USER_ID = 1
DEV_DEVICE_ID = 1

# (카테고리, [소리이름])
SEED_CATALOG: dict[str, list[str]] = {
    "긴급": ["화재 경보", "사이렌", "경보음", "응급차량", "폭발·파열음", "충돌·파손음"],
    "교통": ["자동차 경고음", "급정거·마찰음", "경적", "기차", "차량 주행음", "오토바이", "항공기", "엔진", "기타 이동수단"],
    "사람": ["비명", "울음", "호흡·기침", "신음", "음성", "아기 옹알이", "웃음", "노래", "군중", "발걸음"],
    "생활음": ["가전제품", "욕실 물 소리", "물 튀는 소리", "스프레이", "사무기기", "클릭음", "휙 소리", "바스락", "전자 알림음", "문 닫힘 소리",
            "노크 소리", "열쇠 소리", "충돌·파손음", "공구", "실내 배경음", "타격음", "마찰음", "소음", "냉난방·기계음", "증기"],
    "자연": ["바람·비", "천둥", "나뭇잎 소리", "화산 분출음", "물가"],
    "동물": ["고양이", "개", "새", "가축", "뱀", "벌레", "맹수·야생동물"],
    "주방": ["끓는 소리", "식기", "주방 도구", "조리"],
    "음악": ["대중 음악", "피아노", "현악기", "드럼", "재즈", "클래식"]
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


async def ensure_dev_device(db) -> None:
    """테스트용 디바이스 1개. AI서버/스크립트가 POST /devices/{id}/detections 를
    별도 등록·페어링 절차 없이 고정 id로 바로 쏠 수 있게 시드한다(로그인 우회와 같은 취지)."""
    if await db.get(Device, DEV_DEVICE_ID):
        return
    db.add(Device(
        id=DEV_DEVICE_ID,
        user_id=DEV_USER_ID,
        nickname="개발용 디바이스",
        mac_address="DE:V0:00:00:00:01",
        is_connected=True,
    ))
    await db.commit()


async def seed_sounds(db) -> None:
    """SEED_CATALOG 를 카테고리/소리 테이블에 동기화.

    카탈로그를 편집하고 `python -m app.devinit` 를 다시 돌리면 반영된다.
    내용이 이미 동일하면 그대로 둬서 모드의 소리 선택(mode_sounds)을 보존하고,
    달라졌을 때만 전체 재구성한다(소리 삭제 시 mode_sounds 는 ON DELETE CASCADE 로 정리됨).
    """
    desired = {
        (category_name, name)
        for category_name, sounds in SEED_CATALOG.items()
        for name in sounds
    }
    rows = await db.execute(
        select(SoundCategory.name, Sound.name).join(
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
        for name in sounds:
            db.add(Sound(name=name, category_id=category.id))
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
        await seed_sounds(db)
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
