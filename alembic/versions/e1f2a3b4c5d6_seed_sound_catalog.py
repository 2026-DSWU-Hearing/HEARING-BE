"""소리 카탈로그(카테고리 8 + 소리 67) 시드 — 앱 동작에 필요한 레퍼런스 데이터.

스키마와 함께 `alembic upgrade head` 로 배포되어 운영 DB에도 자동 반영된다.

- 카탈로그를 이 파일에 **고정(freeze)** 한다: 마이그레이션은 특정 시점 상태를 재현해야 하므로
  app 코드(devinit 등)를 import 하지 않고 데이터를 파일 안에 내장한다.
  이후 카탈로그 변경은 이 파일 수정이 아니라 **새 마이그레이션**으로 한다.
- 소리 이름은 AI팀 분류(category_map.py) 한글 이름과 일치시켜 이름기반 매칭이 되게 한다.
- **멱등**: 이미 카테고리가 있으면(기존 devinit 으로 시드된 개발 DB 등) 건너뛴다(중복 삽입 방지).
"""
from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"


# (카테고리, [소리이름]) — 이 마이그레이션 시점의 카탈로그로 고정.
SEED_CATALOG: dict[str, list[str]] = {
    "긴급": ["화재 경보", "사이렌", "경보음", "응급차량", "폭발·파열음", "충돌·파손음"],
    "교통": ["자동차 경고음", "급정거·마찰음", "경적", "기차", "차량 주행음", "오토바이", "항공기", "엔진", "기타 이동수단"],
    "사람": ["비명", "울음", "호흡·기침", "신음", "음성", "아기 옹알이", "웃음", "노래", "군중", "발걸음"],
    "생활음": ["가전제품", "욕실 물 소리", "물 튀는 소리", "스프레이", "사무기기", "클릭음", "휙 소리", "바스락", "전자 알림음", "문 닫힘 소리",
            "노크 소리", "열쇠 소리", "충돌·파손음", "공구", "실내 배경음", "타격음", "마찰음", "소음", "냉난방·기계음", "증기"],
    "자연": ["바람·비", "천둥", "나뭇잎 소리", "화산 분출음", "물가"],
    "동물": ["고양이", "개", "새", "가축", "뱀", "벌레", "맹수·야생동물"],
    "주방": ["끓는 소리", "식기", "주방 도구", "조리"],
    "음악": ["대중 음악", "피아노", "현악기", "드럼", "재즈", "클래식"],
}


def upgrade() -> None:
    bind = op.get_bind()

    # 멱등 가드: 이미 카탈로그가 있으면(기존 개발 DB 등) 중복 삽입하지 않고 종료한다.
    if bind.execute(sa.text("SELECT COUNT(*) FROM sound_categories")).scalar():
        return

    # 경량 테이블 정의(모델 import 없이) — id/타임스탬프는 DB server_default 가 채운다.
    category_table = sa.table("sound_categories", sa.column("name", sa.String))
    sound_table = sa.table(
        "sounds",
        sa.column("name", sa.String),
        sa.column("category_id", sa.Integer),
    )

    op.bulk_insert(category_table, [{"name": name} for name in SEED_CATALOG])

    # 방금 넣은 카테고리 id 를 이름으로 되읽어 소리의 FK 를 채운다(명시적 id 미지정 → 시퀀스 정상).
    rows = bind.execute(sa.text("SELECT id, name FROM sound_categories")).fetchall()
    id_by_name = {name: category_id for category_id, name in rows}

    op.bulk_insert(
        sound_table,
        [
            {"name": sound_name, "category_id": id_by_name[category_name]}
            for category_name, sound_names in SEED_CATALOG.items()
            for sound_name in sound_names
        ],
    )


def downgrade() -> None:
    # 카탈로그 전체 제거. sounds 삭제 시 mode_sounds 는 ON DELETE CASCADE 로 함께 정리된다.
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM sounds"))
    bind.execute(sa.text("DELETE FROM sound_categories"))
