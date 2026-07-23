from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Device(Base, TimestampMixin):
    """물리 기기(넥밴드). 실물이 1대뿐이라 행도 1개만 둔다(id 고정, ensure_physical_device).

    계정별 기기 행을 두던 이전 모델은 연결 상태가 N개 행에 복제돼 동기화 버그
    (등록 시점의 라이브 상태 미반영 등)를 만들었다 → 상태는 이 한 행에만 있다.
    - active_user_id: 알림·진동을 받는 현재 사용자. [기기 연결] 버튼으로만 바뀐다.
    - 기기 이름은 계정별 데이터라 여기 없다 — users.device_nickname 에 산다.
    """

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mac_address: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    active_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    battery_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
