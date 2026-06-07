"""sound icon column (replace icon_url with icon key)

Revision ID: f1a2b3c4d5e6
Revises: 5fba0a496e0b
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '5fba0a496e0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('sounds', 'icon_url')
    op.add_column('sounds', sa.Column('icon', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('sounds', 'icon')
    op.add_column('sounds', sa.Column('icon_url', sa.String(length=500), nullable=True))
