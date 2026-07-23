"""기기 WS 엔드투엔드 스모크 테스트 (PostgreSQL 불필요 — 인메모리 SQLite).

검증 경로 (물리 기기 1행 + active_user 모델의 전체 수명주기):
  조회: GET /devices 가 행을 자가 생성(ensure) — 항상 길이 1
  연결 버튼: 하드웨어 미접속 → 409 즉시 실패 (30초 폴링 없음)
  거절: 토큰 불량 → 4401, 우리 기기가 아닌 MAC → 4404 (핸드셰이크 수락 직후 코드로 닫힘)
  접속(소문자 MAC — 정규화 검증) → is_connected=True (모든 계정이 같은 행을 본다)
  연결 버튼 성공 → 그 계정이 현재 사용자(active user), 입력한 이름은 내 계정에만 저장
  status → battery_level 반영
  감지 POST → active_user 의 활성 모드로 매칭, vibrate(strength=그 사용자의 haptic) 수신
  전환: 다른 계정의 연결 버튼(body 없음) → 덮어쓰기, 이후 감지는 새 사용자 설정으로
  해제: DELETE → active 포인터만 비움 (하드웨어 WS 는 유지), 이후 감지는 스킵
  하드웨어 해제 → is_connected=False

실행:
  python scripts/smoke_device_ws.py
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (어느 cwd에서 실행해도 app 패키지를 찾도록)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.core.security import create_access_token, create_device_token  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.dependencies import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import device, mode, notification, sound, user  # noqa: F401,E402  (메타데이터 등록)
from app.models.sound import Sound, SoundCategory  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import device_service  # noqa: E402
from app.websocket import device_handler  # noqa: E402

MAC = "44:1B:F6:D4:47:F0"

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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSession() as db:
        db.add(User(id=1, email="dev@hearing.local", nickname="dev", terms_agreed=True, haptic_strength=70))
        db.add(User(id=2, email="mate@hearing.local", nickname="mate", terms_agreed=True))  # haptic 기본 50
        db.add(SoundCategory(id=1, name="긴급"))
        await db.flush()
        db.add(Sound(id=1, name="사이렌", category_id=1))
        await db.commit()


def auth(source: str = "user", user_id: int = 1) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, source=source)}"}


def expect_ws_reject(client: TestClient, url: str, expected_code: int) -> None:
    """거절 계약: 핸드셰이크는 수락되고, 첫 수신에서 지정 코드로 닫혀야 한다.
    (accept 전에 close 하면 클라이언트가 코드를 못 받으므로 서버는 accept 후 닫는다)"""
    with client.websocket_connect(url) as ws:
        try:
            ws.receive_text()
        except WebSocketDisconnect as e:
            assert e.code == expected_code, e.code
            return
    raise AssertionError(f"연결이 닫히지 않음 (기대 close {expected_code})")


def get_the_device(client: TestClient, user_id: int) -> dict:
    r = client.get("/devices", headers=auth(user_id=user_id))
    assert r.status_code == 200, r.text
    devices = r.json()
    assert len(devices) == 1, devices
    return devices[0]


def make_active_siren_mode(client: TestClient, user_id: int) -> None:
    r = client.post("/modes", headers=auth(user_id=user_id), json={
        "name": "외출", "icon": "walk", "sounds": [{"sound_id": 1, "name": "사이렌"}],
    })
    assert r.status_code == 200, r.text
    r = client.patch(f"/modes/{r.json()['mode_id']}/activate", headers=auth(user_id=user_id))
    assert r.status_code == 200, r.text


def post_detection(client: TestClient) -> None:
    r = client.post(f"/devices/{device_service.THE_DEVICE_ID}/detections", headers=auth("ai-server"), json={
        "sound_category": "긴급", "sound_name": "사이렌", "confidence": 0.97,
        "direction": "LEFT",
        "detected_at": datetime.now(timezone.utc).isoformat(),
    })
    assert r.status_code == 200, r.text


def notification_count(client: TestClient, user_id: int) -> int:
    r = client.get("/notifications", headers=auth(user_id=user_id))
    assert r.status_code == 200, r.text
    return len(r.json())


def main() -> None:
    import asyncio

    asyncio.run(seed())
    app.dependency_overrides[get_db] = override_get_db
    # 요청 스코프 밖에서 자체 세션을 여는 곳 둘을 교체한다 — 기기 WS 핸들러(수명주기·MAC 해석)와
    # 앱 lifespan(기동 시 물리 기기 행 ensure + 연결 리셋)이 실 DB 대신 인메모리 DB 를 보게.
    import app.main as app_main

    original_session_local = device_handler.AsyncSessionLocal
    original_main_session_local = app_main.AsyncSessionLocal
    device_handler.AsyncSessionLocal = TestSession
    app_main.AsyncSessionLocal = TestSession

    device_token = create_device_token(days=1)
    log: list[tuple[str, object]] = []
    try:
        with TestClient(app) as client:
            # 물리 기기 행은 시드하지 않았다 — 기동(lifespan)의 ensure 가 만들어야 한다
            d = get_the_device(client, 1)
            assert d["id"] == device_service.THE_DEVICE_ID and d["is_connected"] is False, d
            assert d["nickname"] == device_service.DEFAULT_DEVICE_NICKNAME, d
            log.append(("GET /devices ensures the single row", d["id"]))

            # 하드웨어 미접속 상태의 [기기 연결] → 즉시 409 (폴링·타임아웃 없음)
            r = client.post("/devices/connect", headers=auth(), json={"nickname": "내 목걸이"})
            assert r.status_code == 409, f"{r.status_code} {r.text}"
            log.append(("connect before hardware", 409))

            # 감지 매칭용 활성 모드 (두 계정 모두 — 전환 후 감지 라우팅 비교용)
            make_active_siren_mode(client, 1)
            make_active_siren_mode(client, 2)

            # 거절 1: 토큰 불량 → 4401 (user 토큰은 source가 달라 거절돼야 함)
            expect_ws_reject(client, f"/ws/devices?token={create_access_token(1)}&mac={MAC}", 4401)
            log.append(("close on bad token", 4401))

            # 거절 2: 우리 기기가 아닌 MAC → 4404
            expect_ws_reject(client, f"/ws/devices?token={device_token}&mac=FF:FF:FF:FF:FF:FF", 4404)
            log.append(("close on unknown mac", 4404))

            # 정상 수명주기 — 하드웨어가 소문자 MAC 을 보내도 정규화로 매칭돼야 한다
            with client.websocket_connect(f"/ws/devices?token={device_token}&mac={MAC.lower()}") as ws:
                assert get_the_device(client, 1)["is_connected"] is True
                assert get_the_device(client, 2)["is_connected"] is True
                log.append(("is_connected after hardware connect", True))

                # user1 [기기 연결] → 현재 사용자 + 이름 저장 (user2 화면엔 자기 이름/기본값)
                r = client.post("/devices/connect", headers=auth(), json={"nickname": "내 목걸이"})
                assert r.status_code == 200, r.text
                assert r.json()["is_active_user"] is True and r.json()["nickname"] == "내 목걸이", r.text
                mate_view = get_the_device(client, 2)
                assert mate_view["is_active_user"] is False
                assert mate_view["nickname"] == device_service.DEFAULT_DEVICE_NICKNAME
                log.append(("connect switches active user", 1))

                ws.send_text(json.dumps({"type": "status", "battery_level": 77, "connection_type": "hotspot"}))

                # 감지 → active_user(user1) 의 모드로 매칭 → vibrate(strength=70=user1 haptic)
                post_detection(client)
                command = ws.receive_json()
                assert command == {
                    "type": "vibrate", "strength": 70, "sound_name": "사이렌", "sound_category": "긴급",
                    "direction": "LEFT",
                }, command
                assert notification_count(client, 1) == 1 and notification_count(client, 2) == 0
                log.append(("vibrate strength (user1 active)", command["strength"]))

                assert get_the_device(client, 1)["battery_level"] == 77
                log.append(("battery after status", 77))

                # user2 가 [이 계정으로 전환](body 없음) → 덮어쓰기, 이후 감지는 user2 설정으로
                r = client.post("/devices/connect", headers=auth(user_id=2))
                assert r.status_code == 200 and r.json()["is_active_user"] is True, r.text
                assert get_the_device(client, 1)["is_active_user"] is False
                post_detection(client)
                command = ws.receive_json()
                assert command["strength"] == 50, command  # user2 의 haptic 기본값
                assert notification_count(client, 1) == 1 and notification_count(client, 2) == 1
                log.append(("vibrate strength after takeover (user2)", command["strength"]))

                # user2 연결 해제 → active 만 비워지고 하드웨어 WS 는 유지, 이후 감지는 스킵
                r = client.delete(f"/devices/{device_service.THE_DEVICE_ID}", headers=auth(user_id=2))
                assert r.status_code == 200, r.text
                post_detection(client)
                assert notification_count(client, 1) == 1 and notification_count(client, 2) == 1
                ws.send_text(json.dumps({"type": "status", "battery_level": 55}))
                assert get_the_device(client, 2)["battery_level"] == 55  # WS 살아있음 증명
                log.append(("release keeps hardware ws, detection dropped", True))

                # 하드웨어 전원 끔(클라이언트 close) → 서버 finally 의 is_connected=False 커밋을
                # 기다린 뒤 컨텍스트를 나간다. 그냥 나가면 TestClient 가 핸들러 태스크를 취소해
                # 공유 인메모리 SQLite 연결이 쓰기 도중 죽는다(이후 조회 전부 실패).
                ws.close()
                deadline = time.time() + 5
                while get_the_device(client, 1)["is_connected"] and time.time() < deadline:
                    time.sleep(0.05)

            # 하드웨어 해제 → is_connected=False
            assert get_the_device(client, 1)["is_connected"] is False
            log.append(("is_connected after hardware disconnect", False))
    finally:
        app.dependency_overrides.clear()
        device_handler.AsyncSessionLocal = original_session_local
        app_main.AsyncSessionLocal = original_main_session_local
        asyncio.run(engine.dispose())  # aiosqlite 커넥션 스레드 정리 — 없으면 프로세스가 종료되지 않는다

    print("DEVICE WS SMOKE OK")
    for key, value in log:
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
