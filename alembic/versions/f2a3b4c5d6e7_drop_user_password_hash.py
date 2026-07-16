"""drop users.password_hash — 이메일/비번 로그인 제거로 미사용.

Google(GIS)·게스트 로그인만 사용하므로 비밀번호 해시 컬럼을 제거한다.
"""
from alembic import op
import sqlalchemy as sa


revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"


def upgrade() -> None:
    op.drop_column("users", "password_hash")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )
