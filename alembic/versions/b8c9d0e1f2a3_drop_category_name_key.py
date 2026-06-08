"""drop sound category name_key (영문 키 미사용 — FE는 한글 name만 사용)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('sound_categories', 'name_key')


def downgrade() -> None:
    op.add_column('sound_categories', sa.Column('name_key', sa.String(length=50), nullable=True))
