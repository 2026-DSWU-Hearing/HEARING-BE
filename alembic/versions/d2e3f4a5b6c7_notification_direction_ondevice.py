"""notifications.direction / ondevice_vibrated — 알림 목록·푸시에 방향과 온디바이스 여부 노출.

direction 은 감지 payload 로 들어와 진동 명령엔 실려 가면서 DB 에는 안 남았다(기기는 알고
앱은 모르는 비대칭). ondevice_vibrated 는 넥밴드가 먼저 울린 감지를 목록에서 구분하기 위한 값.

기존 행은 방향을 모르므로 'UNKNOWN', 온디바이스 아님(false). 둘 다 NOT NULL — FE 가 null 분기를
따로 두지 않게 한다.
"""

from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("direction", sa.String(length=10), server_default="UNKNOWN", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column("ondevice_vibrated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("notifications", "ondevice_vibrated")
    op.drop_column("notifications", "direction")
