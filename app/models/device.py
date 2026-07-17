from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    # 실물 기기(하드웨어)는 한 대뿐이라 여러 계정이 같은 MAC 을 등록해 공유한다
    # → MAC 전역 unique 는 두지 않고, 같은 계정의 중복 등록만 막는다.
    __table_args__ = (UniqueConstraint("user_id", "mac_address", name="uq_devices_user_mac"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    mac_address: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    battery_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
