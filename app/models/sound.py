from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SoundCategory(Base):
    __tablename__ = "sound_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class Sound(Base, TimestampMixin):
    __tablename__ = "sounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("sound_categories.id"), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)

    category: Mapped[SoundCategory] = relationship(lazy="joined")
