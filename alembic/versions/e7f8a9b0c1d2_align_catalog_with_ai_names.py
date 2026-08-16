"""소리 카탈로그를 AI 가 실제로 내보내는 이름에 맞춘다.

이름 매칭이 AI↔백엔드의 유일한 연결 고리인데, AI(HEARING-MODEL `category_map.py`)가
여러 YAMNet 라벨을 하나로 접는 동안 카탈로그가 옛 이름을 그대로 들고 있어서 양쪽으로 어긋나 있었다.

  - **카탈로그에만 있는 이름** = AI 가 절대 만들어낼 수 없음 → 모드에 넣어도 평생 안 울린다.
  - **AI 만 내는 이름** = 카탈로그에 없음 → `sound_id` 가 null 로 나간다.

어긋난 두 곳을 AI 를 정본으로 삼아 정리한다.

1. 음악: YAMNet 9개 라벨(Music / Electronic music / Piano / Guitar / Violin / Drum /
   Jazz / Classical music / Orchestra)이 전부 `("생활음", "음악")` 하나로 접힌다.
   → 카탈로그의 "대중 음악 / 피아노 / 현악기 / 드럼 / 재즈 / 클래식" 6개를 "음악" 1개로 교체.
   카테고리도 AI 를 따라 "생활음" 으로 가므로 비워진 "음악" 카테고리는 함께 지운다
   (빈 카테고리를 남기면 소리 목록 화면에 항목 없는 섹션이 그대로 뜬다).

2. 주방 도구: 같은 종류의 통합이 이미 일어나 있었다. `Cutlery, silverware`(칼·수저류)가
   `Dishes, pots, and pans` 와 묶여 block "식기" 로 접혀서, AI 의 주방 소리는
   "끓는 소리 / 식기 / 조리" 3개뿐이다. "주방 도구" 는 발화 불가능하므로 지운다.

`mode_sounds` 는 ON DELETE CASCADE 라 삭제된 소리를 참조하던 모드 설정도 함께 정리된다.
어차피 울리지 않던 항목이라 사용자가 잃는 동작은 없다.
"""
from alembic import op
import sqlalchemy as sa


revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"


_OLD_MUSIC_CATEGORY = "음악"
_MUSIC_TARGET_CATEGORY = "생활음"
_MERGED_MUSIC_SOUND = "음악"
_OLD_MUSIC_SOUNDS = ["대중 음악", "피아노", "현악기", "드럼", "재즈", "클래식"]

_KITCHEN_CATEGORY = "주방"
_DEAD_KITCHEN_SOUND = "주방 도구"


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. 음악 6개 → "음악" 1개 -------------------------------------------
    # 카테고리까지 지정해서 지운다 — 다른 카테고리에 같은 이름이 생기더라도 말려들지 않게.
    bind.execute(
        sa.text(
            """
            DELETE FROM sounds
            WHERE name = ANY(:names)
              AND category_id = (SELECT id FROM sound_categories WHERE name = :old_category)
            """
        ),
        {"names": _OLD_MUSIC_SOUNDS, "old_category": _OLD_MUSIC_CATEGORY},
    )

    # AI 가 실제로 보내는 이름을 추가. 이름 기반 매칭이라 이름만 정확하면 된다
    # (icon 은 카탈로그 전체가 비어 있고 FE 가 이름으로 그림을 고른다).
    # 멱등: 이미 있으면 넣지 않는다.
    bind.execute(
        sa.text(
            """
            INSERT INTO sounds (name, category_id)
            SELECT CAST(:name AS varchar), c.id
            FROM sound_categories c
            WHERE c.name = :category
              AND NOT EXISTS (SELECT 1 FROM sounds s WHERE s.name = CAST(:name AS varchar))
            """
        ),
        {"name": _MERGED_MUSIC_SOUND, "category": _MUSIC_TARGET_CATEGORY},
    )

    # 비워진 카테고리 제거. 소리가 남아 있으면 건드리지 않는다(수동으로 뭔가 넣어둔 DB 보호).
    bind.execute(
        sa.text(
            """
            DELETE FROM sound_categories c
            WHERE c.name = :old_category
              AND NOT EXISTS (SELECT 1 FROM sounds s WHERE s.category_id = c.id)
            """
        ),
        {"old_category": _OLD_MUSIC_CATEGORY},
    )

    # --- 2. 발화 불가능한 "주방 도구" 제거 -----------------------------------
    bind.execute(
        sa.text(
            """
            DELETE FROM sounds
            WHERE name = :name
              AND category_id = (SELECT id FROM sound_categories WHERE name = :category)
            """
        ),
        {"name": _DEAD_KITCHEN_SOUND, "category": _KITCHEN_CATEGORY},
    )


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            INSERT INTO sound_categories (name)
            SELECT CAST(:old_category AS varchar)
            WHERE NOT EXISTS (
                SELECT 1 FROM sound_categories WHERE name = CAST(:old_category AS varchar)
            )
            """
        ),
        {"old_category": _OLD_MUSIC_CATEGORY},
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO sounds (name, category_id)
            SELECT unnest(CAST(:names AS text[])), c.id
            FROM sound_categories c
            WHERE c.name = :old_category
            """
        ),
        {"names": _OLD_MUSIC_SOUNDS, "old_category": _OLD_MUSIC_CATEGORY},
    )

    bind.execute(
        sa.text(
            """
            DELETE FROM sounds
            WHERE name = :name
              AND category_id = (SELECT id FROM sound_categories WHERE name = :category)
            """
        ),
        {"name": _MERGED_MUSIC_SOUND, "category": _MUSIC_TARGET_CATEGORY},
    )

    bind.execute(
        sa.text(
            """
            INSERT INTO sounds (name, category_id)
            SELECT CAST(:name AS varchar), c.id
            FROM sound_categories c
            WHERE c.name = :category
              AND NOT EXISTS (SELECT 1 FROM sounds s WHERE s.name = CAST(:name AS varchar))
            """
        ),
        {"name": _DEAD_KITCHEN_SOUND, "category": _KITCHEN_CATEGORY},
    )
