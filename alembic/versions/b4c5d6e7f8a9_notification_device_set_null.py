"""notifications.device_id → nullable + ON DELETE SET NULL, 레거시 기기 행 정리.

기기 삭제 후 재등록이 정식 흐름(등록 버튼)이 되면서 CASCADE 는 알림 히스토리를
통째로 날린다 → 알림은 기기보다 오래 살도록 SET NULL 로 전환.
nullable 이 되면서 게스트 데모 알림도 기기 없이(None) 시드할 수 있다.

레거시 정리: 공유 MAC 모델 이전에 만들어진 기기 행(게스트 랜덤 MAC 시드,
구 스모크/개발 잔여)은 실기기 MAC 과 달라 등록 버튼이 409 로 막히므로 삭제한다.
FK 전환 *이후* 에 지워야 그 기기들의 알림이 CASCADE 로 따라 지워지지 않는다.
(실기기 MAC 하드코딩은 의도 — 이 시점의 일회성 데이터 정리 기록)
"""
from alembic import op
import sqlalchemy as sa


revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"

REAL_DEVICE_MAC = "44:1B:F6:D4:47:F0"


def upgrade() -> None:
    op.alter_column("notifications", "device_id", existing_type=sa.Integer(), nullable=True)
    op.drop_constraint("notifications_device_id_fkey", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "notifications_device_id_fkey",
        "notifications",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(f"DELETE FROM devices WHERE mac_address <> '{REAL_DEVICE_MAC}'")


def downgrade() -> None:
    # NOT NULL 복원을 위해 기기 잃은 알림은 지울 수밖에 없다(정보 손실 — dev 전용 best effort).
    op.execute("DELETE FROM notifications WHERE device_id IS NULL")
    op.drop_constraint("notifications_device_id_fkey", "notifications", type_="foreignkey")
    op.create_foreign_key(
        "notifications_device_id_fkey",
        "notifications",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("notifications", "device_id", existing_type=sa.Integer(), nullable=False)
