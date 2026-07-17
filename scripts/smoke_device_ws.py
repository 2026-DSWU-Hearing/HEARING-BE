"""기기 WS 엔드투엔드 스모크 테스트 (PostgreSQL 불필요 — 인메모리 SQLite).

검증 경로 (WS3 전체 수명주기, 공유 MAC 모델 — MAC 은 서버 설정이 원천, 등록 body 는 nickname 만):
  거절: 토큰 불량 → 4401, 미등록 MAC → 4404 (핸드셰이크 수락 직후 코드로 닫힘 — 실클라이언트도 코드 수신)
  등록: 재등록 → 멱등(같은 id) + 새 이름 반영
        다른 계정 등록 → 허용 (실물 기기 1대를 모든 계정이 공유)
  접속(소문자 MAC 으로 — 정규화 검증) → 그 MAC 을 등록한 모든 계정 is_connected=True
  status → battery_level 이 전 계정 기기 행에 반영
  감지 POST 매칭 → 기기 WS 로 vibrate(strength=haptic_strength) 수신
  삭제: 한 계정이 기기 삭제 → WS 유지 (다른 계정이 공유 중), 마지막 계정 삭제 → 서버가 WS 를 닫음(1000)

실행:
  python scripts/smoke_device_ws.py
"""

import json
import sys
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
        db.add(User(id=2, email="mate@hearing.local", nickname="mate", terms_agreed=True))
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


def get_my_device(client: TestClient, user_id: int) -> dict:
    r = client.get("/devices", headers=auth(user_id=user_id))
    assert r.status_code == 200, r.text
    devices = r.json()
    assert len(devices) == 1, devices
    return devices[0]


def main() -> None:
    import asyncio

    asyncio.run(seed())
    app.dependency_overrides[get_db] = override_get_db
    # 기기 WS 핸들러는 요청 스코프 밖(수명주기·MAC 해석)에서 자체 세션을 쓰므로 직접 교체한다.
    original_session_local = device_handler.AsyncSessionLocal
    device_handler.AsyncSessionLocal = TestSession

    device_token = create_device_token(days=1)
    log: list[tuple[str, object]] = []
    try:
        with TestClient(app) as client:
            # 준비: 두 계정이 같은 실물 기기(MAC)를 등록 + user1 에 모드 생성/활성화 (감지 매칭용)
            r = client.post("/devices", headers=auth(), json={"nickname": "내 목걸이"})
            assert r.status_code == 200, r.text
            device_id = r.json()["id"]

            # 재등록 → 멱등: 새 행을 만들지 않고 기존 기기를 반환하되, 새 이름은 반영한다
            r = client.post("/devices", headers=auth(), json={"nickname": "새 이름 목걸이"})
            assert r.status_code == 200 and r.json()["id"] == device_id, f"{r.status_code} {r.text}"
            assert r.json()["nickname"] == "새 이름 목걸이", r.text
            log.append(("re-register idempotent + renamed", r.json()["nickname"]))

            # 다른 계정이 같은 MAC 등록 → 허용 (공유 기기)
            r = client.post("/devices", headers=auth(user_id=2), json={"nickname": "히어링 디바이스"})
            assert r.status_code == 200, r.text
            mate_device_id = r.json()["id"]
            assert mate_device_id != device_id
            log.append(("shared mac across accounts", mate_device_id))

            r = client.post("/modes", headers=auth(), json={
                "name": "외출", "icon": "walk", "sounds": [{"sound_id": 1, "name": "사이렌"}],
            })
            assert r.status_code == 200, r.text
            client.patch(f"/modes/{r.json()['mode_id']}/activate", headers=auth())

            # 거절 1: 토큰 불량 → 4401 (user 토큰은 source가 달라 거절돼야 함)
            expect_ws_reject(client, f"/ws/devices?token={create_access_token(1)}&mac={MAC}", 4401)
            log.append(("close on bad token", 4401))

            # 거절 2: 미등록 MAC → 4404
            expect_ws_reject(client, f"/ws/devices?token={device_token}&mac=FF:FF:FF:FF:FF:FF", 4404)
            log.append(("close on unknown mac", 4404))

            # 정상 수명주기 — 하드웨어가 소문자 MAC 을 보내도 정규화로 매칭돼야 한다
            with client.websocket_connect(f"/ws/devices?token={device_token}&mac={MAC.lower()}") as ws:
                # 접속 하나로 그 MAC 을 등록한 모든 계정이 연결됨
                assert get_my_device(client, 1)["is_connected"] is True
                assert get_my_device(client, 2)["is_connected"] is True
                log.append(("is_connected after connect (both accounts)", True))

                ws.send_text(json.dumps({"type": "status", "battery_level": 77, "connection_type": "hotspot"}))

                # 감지 매칭 → 이 소켓으로 vibrate 명령이 와야 한다
                r = client.post(f"/devices/{device_id}/detections", headers=auth("ai-server"), json={
                    "sound_category": "긴급", "sound_name": "사이렌", "confidence": 0.97,
                    "direction": "LEFT",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })
                assert r.status_code == 200, r.text
                command = ws.receive_json()
                assert command == {
                    "type": "vibrate", "strength": 70, "sound_name": "사이렌", "sound_category": "긴급",
                    "direction": "LEFT",
                }, command
                log.append(("vibrate strength", command["strength"]))

                assert get_my_device(client, 1)["battery_level"] == 77
                assert get_my_device(client, 2)["battery_level"] == 77
                log.append(("battery after status (both accounts)", 77))

                # user1 이 기기 삭제 → user2 가 아직 공유 중이므로 WS 는 유지된다
                r = client.delete(f"/devices/{device_id}", headers=auth())
                assert r.status_code == 200, r.text
                ws.send_text(json.dumps({"type": "status", "battery_level": 55}))
                assert get_my_device(client, 2)["battery_level"] == 55  # WS 살아있음 증명
                log.append(("ws alive after first delete", True))

                # 마지막 등록 계정(user2)이 삭제 → 서버가 WS 를 닫는다
                r = client.delete(f"/devices/{mate_device_id}", headers=auth(user_id=2))
                assert r.status_code == 200, r.text
                try:
                    ws.receive_json()
                    raise AssertionError("마지막 등록 삭제 후에도 WS 가 살아있음")
                except WebSocketDisconnect as e:
                    assert e.code == 1000, e.code
                    log.append(("close on last delete", e.code))

            # 전부 삭제됐으니 미등록 MAC — 재접속은 4404
            expect_ws_reject(client, f"/ws/devices?token={device_token}&mac={MAC}", 4404)
            log.append(("reconnect after all deleted", 4404))
    finally:
        app.dependency_overrides.clear()
        device_handler.AsyncSessionLocal = original_session_local
        asyncio.run(engine.dispose())  # aiosqlite 커넥션 스레드 정리 — 없으면 프로세스가 종료되지 않는다

    print("DEVICE WS SMOKE OK")
    for key, value in log:
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
