"""흐름 A 엔드투엔드 통합테스트 — 실 PostgreSQL + 실제 앱(엔드포인트) 관통.

scripts/smoke_flow_a.py 가 standalone(인메모리 SQLite)으로 하던 흐름을 pytest 안으로 들여온다:
  디바이스 등록 → 모드 생성/활성화 → 감지 POST(매칭/비매칭) → 알림 필터링 결과 검증.
AI서버 경로 시뮬레이션: sound_id 없이 한글 (category, name)만 보내고 백엔드가 이름으로 해석.
"""

from datetime import datetime, timezone

import pytest

from app.core.security import create_access_token
from app.models.sound import Sound, SoundCategory
from app.models.user import User

USER_ID = 1


def _auth(source: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER_ID, source=source)}"}


async def _seed_user_and_sounds(session_factory, *, do_not_disturb: bool = False) -> None:
    async with session_factory() as db:
        db.add(User(id=USER_ID, email="u@t.local", nickname="u", terms_agreed=True, do_not_disturb=do_not_disturb))
        db.add(SoundCategory(id=1, name="긴급"))
        await db.flush()
        db.add_all([
            Sound(id=1, name="사이렌", category_id=1),
            Sound(id=2, name="초인종", category_id=1),
        ])
        await db.commit()


async def _make_active_mode_with_siren(client) -> int:
    """사이렌만 포함한 모드를 만들고 활성화한다. device_id 반환."""
    r = await client.post("/devices", headers=_auth(), json={"nickname": "목걸이"})
    assert r.status_code == 200, r.text
    device_id = r.json()["id"]

    r = await client.post("/modes", headers=_auth(), json={"name": "외출", "icon": "walk", "sounds": [{"sound_id": 1}]})
    assert r.status_code == 200, r.text
    mode_id = r.json()["mode_id"]

    r = await client.patch(f"/modes/{mode_id}/activate", headers=_auth())
    assert r.status_code == 200 and r.json()["is_active"] is True, r.text
    return device_id


def _detection(sound_name: str) -> dict:
    return {
        "sound_category": "긴급",
        "sound_name": sound_name,
        "confidence": 0.95,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.asyncio
async def test_matched_detection_is_saved_and_unmatched_ignored(api_client):
    client, session_factory = api_client
    await _seed_user_and_sounds(session_factory)
    device_id = await _make_active_mode_with_siren(client)

    # 매칭: 사이렌 → 이름으로 sound_id=1 해석 → 활성 모드에 포함 → 알림 저장
    r = await client.post(f"/devices/{device_id}/detections", headers=_auth("ai-server"), json=_detection("사이렌"))
    assert r.status_code == 200, r.text
    # 비매칭: 초인종 → sound_id=2 → 활성 모드에 없음 → 무시
    r = await client.post(f"/devices/{device_id}/detections", headers=_auth("ai-server"), json=_detection("초인종"))
    assert r.status_code == 200, r.text

    r = await client.get("/notifications", headers=_auth())
    assert r.status_code == 200, r.text
    notifs = r.json()
    assert len(notifs) == 1  # 매칭 1건만 저장
    assert notifs[0]["sound_name"] == "사이렌"


@pytest.mark.asyncio
async def test_do_not_disturb_suppresses_everything(api_client):
    client, session_factory = api_client
    await _seed_user_and_sounds(session_factory, do_not_disturb=True)
    device_id = await _make_active_mode_with_siren(client)

    r = await client.post(f"/devices/{device_id}/detections", headers=_auth("ai-server"), json=_detection("사이렌"))
    assert r.status_code == 200, r.text

    r = await client.get("/notifications", headers=_auth())
    assert r.json() == []  # 방해금지면 매칭돼도 기록조차 남기지 않음


@pytest.mark.asyncio
async def test_device_delete_keeps_notification_history(api_client):
    """기기 삭제(→재등록이 정식 흐름)가 알림 히스토리를 지우면 안 된다 — device_id 만 NULL 로 남는다."""
    client, session_factory = api_client
    await _seed_user_and_sounds(session_factory)
    device_id = await _make_active_mode_with_siren(client)

    r = await client.post(f"/devices/{device_id}/detections", headers=_auth("ai-server"), json=_detection("사이렌"))
    assert r.status_code == 200, r.text

    r = await client.delete(f"/devices/{device_id}", headers=_auth())
    assert r.status_code == 200, r.text

    r = await client.get("/notifications", headers=_auth())
    notifs = r.json()
    assert len(notifs) == 1  # 기기가 사라져도 감지 기록은 남는다
    assert notifs[0]["sound_name"] == "사이렌"
    assert notifs[0]["device_id"] is None
