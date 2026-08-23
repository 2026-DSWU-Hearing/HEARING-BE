from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    """소리 감지 결과 알림. 두 경로(웨어러블 온디바이스 AI, HEARING-AI-SE) 모두 여기에 저장.

    행은 계정 단위다(감지 시점의 active_user 한 명 앞으로만 만들어진다). 그래서 알림 삭제는
    물리 삭제만으로 계정 간 격리가 성립한다 — 같은 넥밴드를 쓰는 다른 계정의 목록은 변하지
    않으므로 사용자별 숨김 테이블이 따로 필요 없다.
    """

    __tablename__ = "notifications"

    # 목록 조회는 항상 (user_id 고정 + detected_at DESC, id DESC 정렬 + 커서 절단)이라
    # 세 컬럼을 한 인덱스로 덮는다. ASC 로 만들어도 PostgreSQL 이 역방향 스캔으로 쓰므로
    # DESC 인덱스를 따로 둘 필요는 없다.
    # user_id 단일 인덱스는 이 인덱스의 선행 컬럼이라 중복이므로 마이그레이션에서 지웠다.
    __table_args__ = (
        Index("ix_notifications_user_id_detected_at_id", "user_id", "detected_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # 알림(감지 기록)은 기기보다 오래 산다 — 기기 삭제 후 재등록이 정식 흐름이라
    # CASCADE 면 히스토리가 통째로 날아간다. 게스트 데모 알림도 기기 없이(None) 시드된다.
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    sound_id: Mapped[int | None] = mapped_column(ForeignKey("sounds.id"), nullable=True)

    sound_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sound_category: Mapped[str] = mapped_column(String(50), nullable=False)

    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # 널 금지 — FE 는 confidence 가 널이면 그 페이지 전체를 무효로 보고 목록을 비운다.
    # 수신 단계(DetectionCreate)에서도 필수라 여기까지 널이 올 수 없다.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
