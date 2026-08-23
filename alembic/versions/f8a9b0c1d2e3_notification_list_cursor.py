"""알림 목록 API(커서 페이지네이션)를 위한 스키마 정리.

세 가지를 한다.

1. confidence NOT NULL + 기존 널 백필
   FE 검증기는 confidence 가 널이면 그 값이 실린 **페이지 전체**를 잘못된 응답으로 보고
   알림 목록을 빈 배열로 만든다(항목 하나가 빠지는 게 아니라 화면이 통째로 빈다). 응답
   계층에서 0 으로 바꿔치기하면 없는 데이터를 지어내는 셈이라, 애초에 널이 못 들어오게
   컬럼에서 막는다(수신 스키마 DetectionCreate 에서도 필수).
   유일한 생산자인 AI 서버는 항상 score 를 보내므로 널 행은 초기 수동 테스트 잔재뿐이고,
   알림 화면은 confidence 를 표시하지 않으므로 0 백필로 보이는 값이 달라지지 않는다.

2. (user_id, detected_at, id) 복합 인덱스
   목록 쿼리가 항상 `WHERE user_id=? AND (detected_at, id) < (?, ?)
   ORDER BY detected_at DESC, id DESC` 라 이 인덱스가 없으면 해당 계정 알림을 전부 읽어
   정렬한다. ASC 로 만들어도 PostgreSQL 이 역방향 스캔으로 쓰므로 DESC 인덱스는 불필요.

3. user_id 단일 인덱스 제거
   위 복합 인덱스의 선행 컬럼이라 완전히 중복이다. 남겨두면 INSERT 마다 쓰기 비용만 든다.
"""

from alembic import op
import sqlalchemy as sa


revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"

_COMPOSITE_INDEX = "ix_notifications_user_id_detected_at_id"
_USER_ID_INDEX = "ix_notifications_user_id"


def upgrade() -> None:
    op.execute("UPDATE notifications SET confidence = 0 WHERE confidence IS NULL")
    op.alter_column(
        "notifications",
        "confidence",
        existing_type=sa.Float(),
        nullable=False,
    )

    op.create_index(
        _COMPOSITE_INDEX,
        "notifications",
        ["user_id", "detected_at", "id"],
        unique=False,
    )
    # 복합 인덱스를 만든 뒤에 지운다 — 순서가 반대면 그 사이 목록 쿼리가 인덱스 없이 돈다.
    op.drop_index(_USER_ID_INDEX, table_name="notifications")


def downgrade() -> None:
    op.create_index(_USER_ID_INDEX, "notifications", ["user_id"], unique=False)
    op.drop_index(_COMPOSITE_INDEX, table_name="notifications")
    # 백필로 0 이 된 행은 원래 널이었는지 알 수 없으므로 되돌리지 않는다.
    op.alter_column(
        "notifications",
        "confidence",
        existing_type=sa.Float(),
        nullable=True,
    )
