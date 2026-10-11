"""users.location_agreed — 위치정보 이용 동의.

온보딩·양방향 소통 모달에서 받는 동의다. FE 가 localStorage 에 들고 있던 값을 서버로 옮긴다
(기기 변경·캐시 삭제에도 동의 상태가 유지되게). 기존 사용자·게스트는 동의한 적이 없으므로 false.
"""

from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("location_agreed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "location_agreed")
