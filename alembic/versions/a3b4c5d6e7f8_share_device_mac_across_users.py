"""devices.mac_address 전역 unique 해제 — 실물 기기 1대를 모든 계정이 공유.

하드웨어는 한 대뿐이라 계정마다 같은 MAC 의 기기 행을 갖는다(로그인 시 자동 보장).
- 전역 unique 제거, 조회용 일반 인덱스 추가 (WS 접속 시 MAC 으로 등록 여부 확인)
- 같은 계정의 중복 등록만 막는 복합 unique (user_id, mac_address) 추가
- 과거 PATCH·시드로 오염된 is_connected=true 잔존값 일괄 정리
  (이후로는 기기 WS 수명주기 + 서버 기동 시 리셋이 관리한다)
"""
from alembic import op
import sqlalchemy as sa


revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"


def upgrade() -> None:
    op.drop_constraint("devices_mac_address_key", "devices", type_="unique")
    op.create_index(op.f("ix_devices_mac_address"), "devices", ["mac_address"], unique=False)
    op.create_unique_constraint("uq_devices_user_mac", "devices", ["user_id", "mac_address"])
    op.execute("UPDATE devices SET is_connected = false WHERE is_connected = true")


def downgrade() -> None:
    # 여러 계정이 같은 MAC 을 이미 공유 중이면 전역 unique 복원은 실패한다(데이터 정리 필요).
    op.drop_constraint("uq_devices_user_mac", "devices", type_="unique")
    op.drop_index(op.f("ix_devices_mac_address"), table_name="devices")
    op.create_unique_constraint("devices_mac_address_key", "devices", ["mac_address"])
