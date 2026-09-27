"""users.emergency_alert_enabled — "긴급 소리 알림 받기" 토글.

넥밴드의 온디바이스 AI 를 켜고 끄는 계정별 설정이다. 꺼져 있으면 넥밴드가 기기 내 추론을
건너뛰고, 소리 판단은 종전대로 AI 서버 → 백엔드 경로만 탄다.

기본값 true: 넥밴드 펌웨어의 기본값(설정 수신 전·오프라인)과 맞춘다. 어긋나면 넥밴드가
백엔드에 붙는 순간 동작이 바뀌어 사용자는 이유를 알 수 없다.
"""

from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("emergency_alert_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "emergency_alert_enabled")
