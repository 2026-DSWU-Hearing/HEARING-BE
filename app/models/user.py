from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    disability_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    haptic_strength: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    do_not_disturb: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    fcm_token: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_google_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    terms_agreed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
