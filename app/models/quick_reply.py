from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class QuickReply(Base, TimestampMixin):
    """자주 쓰는 답변. 계정별 문구 목록 — 대화 화면에서 골라 오른쪽 버블로 보낸다."""

    __tablename__ = "quick_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(String(200), nullable=False)
