"""drop risk_level (위험도 미사용 — HW·FE·백엔드 모두 안 씀)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('sounds', 'risk_level')
    op.drop_column('notifications', 'risk_level')


def downgrade() -> None:
    op.add_column('notifications', sa.Column('risk_level', sa.String(length=10), nullable=False, server_default='LOW'))
    op.add_column('sounds', sa.Column('risk_level', sa.String(length=10), nullable=False, server_default='LOW'))
