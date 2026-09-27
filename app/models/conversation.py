from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    """양방향 소통(STT 대화) 한 건. 마이크를 켜기 전에 만들어지고(STT 소켓 주소에 id 가 필요),
    [대화 종료] 때 버블 전체가 한 번에 붙으면서 ended_at 이 찍힌다.

    좌표는 받은 그대로 저장한다 — 좌표→장소 이름 변환은 FE 몫(합의). 위치 권한 거부·실내라
    둘 다 null 인 경우가 정상 입력이므로 null 허용."""

    __tablename__ = "conversations"

    # 목록은 항상 (user_id 고정 + started_at DESC) — 알림 목록 인덱스와 같은 이유로 복합 인덱스 하나.
    __table_args__ = (Index("ix_conversations_user_id_started_at", "user_id", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # 종료 전에는 둘 다 NULL. 종료 시 서버가 버블로부터 만든다(휴리스틱 — conversation_service).
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(300), nullable=True)

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bubbles: Mapped[list["ConversationBubble"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationBubble.seq",
    )


class ConversationBubble(Base, TimestampMixin):
    """대화 말풍선. 종료 시 일괄 업로드되므로 created_at 은 전부 업로드 시각이다 — 발화 순서의
    진실은 seq(요청 배열 순서)뿐이라 정렬은 항상 seq 로 한다."""

    __tablename__ = "conversation_bubbles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'left'(상대방) | 'right'(나) — 화면 배치 그대로. 값 검증은 스키마(BubbleDirection)가 한다.
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    # 'text' | 'stt' | 'favorite_answer'
    input_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="bubbles")
