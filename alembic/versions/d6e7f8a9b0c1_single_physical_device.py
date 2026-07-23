"""물리 기기 1행 + active_user 모델 전환.

계정별 기기 행(공유 MAC)은 연결 상태를 N개 행에 복제해 동기화 버그를 만들었고
(하드웨어가 먼저 접속해 있으면 나중에 등록한 행이 영영 미연결), 감지 라우팅도
"기기 행 = 받는 계정" 이라는 낡은 1:1 가정에 묶여 있었다.
→ 기기 행은 물리 기기당 1개만 두고, 알림·진동 대상은 active_user_id 한 명
  ([기기 연결] 버튼으로만 전환), 기기 이름은 계정별 users.device_nickname 으로 이관.

행 자체는 앱 기동/devinit 의 ensure_physical_device 가 만든다(마이그레이션은
스키마 전환 + 이름 이관 + 계정별 행 정리만).
"""
from alembic import op
import sqlalchemy as sa


revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"


def upgrade() -> None:
    # 계정별 기기 이름 → 계정으로 이관 (계정당 기기 1행이었으므로 1:1)
    op.add_column("users", sa.Column("device_nickname", sa.String(50), nullable=True))
    op.execute(
        "UPDATE users SET device_nickname = d.nickname FROM devices d WHERE d.user_id = users.id"
    )

    # 계정별 행 제거 — notifications.device_id 는 ON DELETE SET NULL(b4c5 계약)이라 히스토리는 남는다
    op.execute("DELETE FROM devices")
    op.drop_constraint("uq_devices_user_mac", "devices", type_="unique")
    op.drop_column("devices", "user_id")
    op.drop_column("devices", "nickname")

    op.add_column("devices", sa.Column("active_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "devices_active_user_id_fkey",
        "devices",
        "users",
        ["active_user_id"],
        ["id"],
        ondelete="SET NULL",  # 현재 사용자 계정이 지워지면 포인터만 비운다
    )

    # 물리 기기당 1행이므로 MAC 은 다시 전역 unique (a3b4 에서 풀었던 것을 단일 행 전제로 복원)
    op.drop_index(op.f("ix_devices_mac_address"), table_name="devices")
    op.create_index(op.f("ix_devices_mac_address"), "devices", ["mac_address"], unique=True)


def downgrade() -> None:
    # 행의 의미(물리 기기)가 달라 계정별 행은 복원 불가 — 비우고 스키마만 되돌린다(dev best effort).
    op.execute("DELETE FROM devices")
    op.drop_index(op.f("ix_devices_mac_address"), table_name="devices")
    op.create_index(op.f("ix_devices_mac_address"), "devices", ["mac_address"], unique=False)
    op.drop_constraint("devices_active_user_id_fkey", "devices", type_="foreignkey")
    op.drop_column("devices", "active_user_id")
    op.add_column("devices", sa.Column("nickname", sa.String(50), nullable=False))
    op.add_column("devices", sa.Column("user_id", sa.Integer(), nullable=False))
    op.create_foreign_key(
        "devices_user_id_fkey", "devices", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_unique_constraint("uq_devices_user_mac", "devices", ["user_id", "mac_address"])
    op.drop_column("users", "device_nickname")
