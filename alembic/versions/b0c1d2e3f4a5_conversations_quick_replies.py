"""양방향 소통: 대화·말풍선·자주 쓰는 답변 테이블.

  - 대화는 latitude/longitude(원좌표, null 허용)와 summary 를 들고 location(장소명)은 없다 —
    좌표→장소 이름 변환은 FE 가 한다.
  - 말풍선은 종료 시 일괄 업로드라 seq(요청 배열 순서)가 발화 순서의 진실이다.
  - 자주 쓰는 답변은 정렬 컬럼 없이 id 순.
"""

from alembic import op
import sqlalchemy as sa


revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=True),
        sa.Column("summary", sa.String(length=300), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_user_id_started_at", "conversations", ["user_id", "started_at"])

    op.create_table(
        "conversation_bubbles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("input_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_conversation_bubbles_conversation_id", "conversation_bubbles", ["conversation_id"]
    )

    op.create_table(
        "quick_replies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_quick_replies_user_id", "quick_replies", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_quick_replies_user_id", table_name="quick_replies")
    op.drop_table("quick_replies")
    op.drop_index("ix_conversation_bubbles_conversation_id", table_name="conversation_bubbles")
    op.drop_table("conversation_bubbles")
    op.drop_index("ix_conversations_user_id_started_at", table_name="conversations")
    op.drop_table("conversations")
