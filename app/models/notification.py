from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    """소리 감지 결과 알림. 두 경로(웨어러블 온디바이스 AI, HEARING-AI-SE) 모두 여기에 저장."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # 알림(감지 기록)은 기기보다 오래 산다 — 기기 삭제 후 재등록이 정식 흐름이라
    # CASCADE 면 히스토리가 통째로 날아간다. 게스트 데모 알림도 기기 없이(None) 시드된다.
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    sound_id: Mapped[int | None] = mapped_column(ForeignKey("sounds.id"), nullable=True)

    sound_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sound_category: Mapped[str] = mapped_column(String(50), nullable=False)

    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
