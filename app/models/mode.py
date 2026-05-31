from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.sound import Sound


class Mode(Base, TimestampMixin):
    __tablename__ = "modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    icon: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    sound_links: Mapped[list["ModeSound"]] = relationship(
        back_populates="mode", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def sounds(self) -> list["Sound"]:
        """ModeResponse.sounds 직렬화용 — 연결행(ModeSound)이 아니라 실제 Sound 목록을 반환."""
        return [link.sound for link in self.sound_links]


class ModeSound(Base):
    __tablename__ = "mode_sounds"
    __table_args__ = (UniqueConstraint("mode_id", "sound_id", name="uq_mode_sound"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode_id: Mapped[int] = mapped_column(ForeignKey("modes.id", ondelete="CASCADE"), nullable=False)
    sound_id: Mapped[int] = mapped_column(ForeignKey("sounds.id", ondelete="CASCADE"), nullable=False)

    mode: Mapped[Mode] = relationship(back_populates="sound_links")
    sound: Mapped["Sound"] = relationship(lazy="joined")
