from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b0'
down_revision = 'd0e1f2a3b4c5'


def upgrade() -> None:
    # 기존 사용자의 값은 유지하고, 이후 INSERT의 DB 기본값만 false로 바꾼다.
    op.alter_column(
        'users',
        'push_enabled',
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )


def downgrade() -> None:
    op.alter_column(
        'users',
        'push_enabled',
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.true(),
    )
