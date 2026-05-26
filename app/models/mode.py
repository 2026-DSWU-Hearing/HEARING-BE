from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Mode(Base, TimestampMixin):
    __tablename__ = "modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    icon: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    sounds: Mapped[list["ModeSound"]] = relationship(
        back_populates="mode", cascade="all, delete-orphan", lazy="selectin"
    )


class ModeSound(Base):
    __tablename__ = "mode_sounds"
    __table_args__ = (UniqueConstraint("mode_id", "sound_id", name="uq_mode_sound"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode_id: Mapped[int] = mapped_column(ForeignKey("modes.id", ondelete="CASCADE"), nullable=False)
    sound_id: Mapped[int] = mapped_column(ForeignKey("sounds.id", ondelete="CASCADE"), nullable=False)

    mode: Mapped[Mode] = relationship(back_populates="sounds")
