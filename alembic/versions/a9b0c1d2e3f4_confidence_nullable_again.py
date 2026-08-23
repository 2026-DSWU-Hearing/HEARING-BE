"""confidence 를 다시 널 허용으로 되돌린다.

f8a9b0c1d2e3 에서 NOT NULL 로 막았던 것을 되돌리는 마이그레이션이다. 그 리비전은 이미 dev 에
머지돼 팀원 DB 에 적용됐을 수 있으므로 수정하지 않고 새 리비전으로 되돌린다.

왜 되돌리나: NOT NULL 은 수신 단계에서 confidence 없는 감지를 422 로 거절하게 만든다.
화면에 표시하지도 않는 메타데이터 하나 때문에 감지가 통째로 사라지는데, 청각보조 앱에서
화재 경보를 잃는 손해가 훨씬 크다. 널을 허용하고 경고 로그로 프로듀서 문제를 드러내는 쪽이
실패했을 때 손해가 작다. FE 도 confidence 를 `number | null` 로 받기로 합의했다.

인덱스(ix_notifications_user_id_detected_at_id)는 그대로 둔다 — 커서 페이지네이션에 계속 필요하다.
"""

from alembic import op
import sqlalchemy as sa


revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"


def upgrade() -> None:
    op.alter_column(
        "notifications",
        "confidence",
        existing_type=sa.Float(),
        nullable=True,
    )


def downgrade() -> None:
    # 되돌리려면 널을 다시 메워야 NOT NULL 이 걸린다(f8a9b0c1d2e3 과 같은 처리).
    op.execute("UPDATE notifications SET confidence = 0 WHERE confidence IS NULL")
    op.alter_column(
        "notifications",
        "confidence",
        existing_type=sa.Float(),
        nullable=False,
    )
