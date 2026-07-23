"""흐름 A 엔드투엔드 스모크 테스트 (PostgreSQL 불필요 — 인메모리 SQLite).

검증 경로:
  유저 조회 → 모드 생성/활성화 → 감지 POST(매칭/비매칭) → 알림 필터링.
  (물리 기기 행 1개를 active_user=1 로 시드 — 감지는 그 현재 사용자에게 라우팅된다)

핵심 단언:
  - POST /modes 응답의 sounds 가 실제 Sound 목록으로 직렬화된다(ModeResponse 버그 회귀 방지).
  - AI서버 경로: sound_id 없이 한글 (category, name)만 와도 백엔드가 이름으로 sound_id 를 해석한다.
  - 활성 모드에 포함된 소리만 Notification 으로 저장된다(비매칭은 무시).

실행:
  python scripts/smoke_flow_a.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (어느 cwd에서 실행해도 app 패키지를 찾도록)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.dependencies import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import device, mode, notification, sound, user  # noqa: F401,E402  (메타데이터 등록)
from app.models.device import Device  # noqa: E402
from app.models.sound import Sound, SoundCategory  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.device_service import THE_DEVICE_ID  # noqa: E402

# StaticPool + 단일 연결이라야 인메모리 DB가 모든 세션에서 공유된다.
engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSession() as session:
        yield session


async def seed() -> None:
    async with TestSession() as db:
        db.add(User(id=1, email="dev@hearing.local", nickname="dev", terms_agreed=True))
        db.add(SoundCategory(id=1, name="위험"))
        await db.flush()
        db.add_all([
            Sound(id=1, name="화재경보기", category_id=1),
            Sound(id=2, name="초인종", category_id=1),
            Sound(id=3, name="사이렌", category_id=1),
        ])
        # 물리 기기 행(1개) — user1 이 [기기 연결]을 마친 상태로 시드
        db.add(Device(id=THE_DEVICE_ID, mac_address=settings.DEVICE_MAC_ADDRESS, active_user_id=1))
        await db.commit()


def auth(source: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(1, source=source)}"}


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed()
    app.dependency_overrides[get_db] = override_get_db

    log: list[tuple[str, object]] = []
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/users/me", headers=auth())
            assert r.status_code == 200, r.text
            log.append(("GET /users/me nickname", r.json()["nickname"]))

            r = await c.get("/devices", headers=auth())
            assert r.status_code == 200, r.text
            device_id = r.json()[0]["id"]
            assert device_id == THE_DEVICE_ID and r.json()[0]["is_active_user"] is True, r.text
            log.append(("GET /devices id (active user)", device_id))

            r = await c.post(
                "/modes",
                headers=auth(),
                json={
                    "name": "외출",
                    "icon": "walk",
                    "sounds": [{"sound_id": 1, "name": "화재경보기"}, {"sound_id": 3, "name": "사이렌"}],
                },
            )
            assert r.status_code == 200, r.text  # <-- ModeWriteResponse 직렬화 버그면 여기서 500
            mode_id = r.json()["mode_id"]
            log.append(("POST /modes sounds", [s["name"] for s in r.json()["sounds"]]))

            r = await c.patch(f"/modes/{mode_id}/activate", headers=auth())
            assert r.status_code == 200 and r.json()["is_active"] is True, r.text

            # AI서버 경로 시뮬레이션: sound_id 없이 한글 (category, name)만 보낸다(source=ai-server).
            base_det = {
                "sound_category": "위험",
                "confidence": 0.97,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            # 매칭: "화재경보기" → 이름으로 sound_id=1 해석 → 활성 모드에 포함 → 알림 저장
            r = await c.post(f"/devices/{device_id}/detections", headers=auth("ai-server"),
                             json={**base_det, "sound_name": "화재경보기"})
            assert r.status_code == 200, r.text
            # 비매칭: "초인종" → sound_id=2 해석 → 활성 모드에 없음 → 무시
            r = await c.post(f"/devices/{device_id}/detections", headers=auth("ai-server"),
                             json={**base_det, "sound_name": "초인종"})
            assert r.status_code == 200, r.text

            r = await c.get("/notifications", headers=auth())
            assert r.status_code == 200, r.text
            notifs = r.json()
            log.append(("GET /notifications count", len(notifs)))
            assert len(notifs) == 1, f"매칭 1건만 저장돼야 함, got {len(notifs)}: {notifs}"
            assert notifs[0]["sound_name"] == "화재경보기", notifs[0]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()  # aiosqlite 커넥션 스레드 정리 — 없으면 프로세스가 종료되지 않는다

    print("SMOKE OK")
    for key, value in log:
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
