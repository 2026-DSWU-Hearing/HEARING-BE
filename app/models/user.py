from sqlalchemy import Boolean, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    disability_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 기기 이름은 계정별 데이터 — 물리 기기(devices)는 1행뿐이라 각자 자기가 지은 이름으로 본다.
    # NULL 이면 기본 표시명(device_service.DEFAULT_DEVICE_NICKNAME)으로 응답한다.
    device_nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)

    haptic_strength: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    do_not_disturb: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )

    fcm_token: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_google_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    terms_agreed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
