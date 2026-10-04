"""흐름 A 엔드투엔드 통합테스트 — 실 PostgreSQL + 실제 앱(엔드포인트) 관통.

scripts/smoke_flow_a.py 가 standalone(인메모리 SQLite)으로 하던 흐름을 pytest 안으로 들여온다:
  모드 생성/활성화 → 감지 POST(매칭/비매칭) → 알림 필터링 결과 검증.
감지는 물리 기기 행(1개)의 active_user 에게만 라우팅된다 — 현재 사용자가 없으면 스킵.
AI서버 경로 시뮬레이션: sound_id 없이 한글 (category, name)만 보내고 백엔드가 이름으로 해석.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.device import Device
from app.models.notification import Notification
from app.models.sound import Sound
from app.models.user import User
from app.services.device_service import THE_DEVICE_ID

USER_ID = 1

# 카탈로그 실제 소리. 긴급 알림 토글이 켜져 있으면(기본값) 긴급 카테고리는 모드 필터를 건너뛰므로,
# "모드 밖이라 무시"를 보려면 생활음 쪽 소리를 써야 한다.
MATCHED = "사이렌"  # 긴급, 활성 모드에 포함
UNMATCHED_EMERGENCY = "경보음"  # 긴급, 활성 모드에 없음 → 토글 ON 이면 우회 저장
UNMATCHED_DAILY = ("생활음", "가전제품")  # 생활음, 활성 모드에 없음 → 항상 무시


def _auth(source: str = "user", user_id: int = USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, source=source)}"}


async def _seed(
    session_factory,
    *,
    do_not_disturb: bool = False,
    emergency_alert_enabled: bool = True,
    active_user_id: int | None = USER_ID,
) -> None:
    """유저 + 물리 기기 행. active_user_id=None 이면 '아무도 연결 안 한' 상태.
    소리 카탈로그는 conftest 가 마이그레이션으로 깔아둔 실물을 쓴다(여기서 만들지 않는다)."""
    async with session_factory() as db:
        db.add(
            User(
                id=USER_ID,
                email="u@t.local",
                nickname="u",
                terms_agreed=True,
                do_not_disturb=do_not_disturb,
                emergency_alert_enabled=emergency_alert_enabled,
            )
        )
        await db.flush()  # devices.active_user_id FK — 유저가 먼저 들어가야 한다
        db.add(Device(id=THE_DEVICE_ID, mac_address=settings.DEVICE_MAC_ADDRESS, active_user_id=active_user_id))
        await db.commit()


async def _sound_id(session_factory, name: str) -> int:
    async with session_factory() as db:
        return (await db.execute(select(Sound.id).where(Sound.name == name))).scalar_one()


async def _make_active_mode_with_siren(client, session_factory) -> None:
    """사이렌만 포함한 모드를 만들고 활성화한다."""
    siren_id = await _sound_id(session_factory, MATCHED)
    r = await client.post(
        "/modes", headers=_auth(), json={"name": "외출", "icon": "walk", "sounds": [{"sound_id": siren_id}]}
    )
    assert r.status_code == 200, r.text
    mode_id = r.json()["mode_id"]

    r = await client.patch(f"/modes/{mode_id}/activate", headers=_auth())
    assert r.status_code == 200 and r.json()["is_active"] is True, r.text


def _detection(sound_name: str, category: str = "긴급") -> dict:
    return {
        "sound_category": category,
        "sound_name": sound_name,
        "confidence": 0.95,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.asyncio
async def test_matched_detection_is_saved_and_unmatched_ignored(api_client):
    client, session_factory = api_client
    await _seed(session_factory)
    await _make_active_mode_with_siren(client, session_factory)

    # 매칭: 사이렌 → 이름으로 sound_id 해석 → 활성 모드에 포함 → 알림 저장
    r = await client.post(f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(MATCHED))
    assert r.status_code == 200, r.text
    # 비매칭: 가전제품(생활음) → 이름으로 해석은 되지만 활성 모드에 없음 → 무시
    r = await client.post(
        f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(*UNMATCHED_DAILY)
    )
    assert r.status_code == 200, r.text

    r = await client.get("/notifications", headers=_auth())
    assert r.status_code == 200, r.text
    notifs = r.json()["items"]
    assert len(notifs) == 1  # 매칭 1건만 저장
    assert notifs[0]["sound_name"] == MATCHED


@pytest.mark.asyncio
async def test_do_not_disturb_suppresses_everything(api_client):
    client, session_factory = api_client
    await _seed(session_factory, do_not_disturb=True)
    await _make_active_mode_with_siren(client, session_factory)

    r = await client.post(f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(MATCHED))
    assert r.status_code == 200, r.text

    r = await client.get("/notifications", headers=_auth())
    assert r.json()["items"] == []  # 방해금지면 매칭돼도 기록조차 남기지 않음


@pytest.mark.asyncio
async def test_detection_without_active_user_is_dropped(api_client):
    """아무도 [기기 연결]을 안 눌렀으면(active_user 없음) 감지는 조용히 스킵된다 — 200 이지만 기록 없음."""
    client, session_factory = api_client
    await _seed(session_factory, active_user_id=None)
    await _make_active_mode_with_siren(client, session_factory)

    r = await client.post(f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(MATCHED))
    assert r.status_code == 200, r.text

    r = await client.get("/notifications", headers=_auth())
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_release_keeps_history_and_stops_future_alerts(api_client):
    """연결 해제(DELETE) 후에도 알림 히스토리는 남고, 이후 감지는 더 이상 나에게 오지 않는다."""
    client, session_factory = api_client
    await _seed(session_factory)
    await _make_active_mode_with_siren(client, session_factory)

    r = await client.post(f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(MATCHED))
    assert r.status_code == 200, r.text

    r = await client.delete(f"/devices/{THE_DEVICE_ID}", headers=_auth())
    assert r.status_code == 200, r.text

    r = await client.post(f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(MATCHED))
    assert r.status_code == 200, r.text

    r = await client.get("/notifications", headers=_auth())
    notifs = r.json()["items"]
    assert len(notifs) == 1  # 해제 전 기록은 유지, 해제 후 감지는 미기록
    assert notifs[0]["sound_name"] == MATCHED

    # device_id 는 FE 응답에 없다(WS 페이로드와 필드를 맞추느라 뺐다) — DB 로 직접 본다.
    async with session_factory() as db:
        device_ids = (await db.execute(select(Notification.device_id))).scalars().all()
    assert list(device_ids) == [THE_DEVICE_ID]  # 행이 삭제되지 않으므로 참조도 그대로


# --- 온디바이스 긴급 판정(ondevice_vibrated) ---------------------------------------
# 넥밴드의 온디바이스 AI 가 몇몇 소리를 먼저 긴급으로 판정해 스스로 진동한다. 그 감지는
# 웹앱 사후 알림(저장·푸시)만 하고 진동 명령은 다시 보내지 않는다.


def _ondevice_detection(sound_name: str, category: str = "긴급") -> dict:
    return {**_detection(sound_name, category), "ondevice_vibrated": True}


@pytest.fixture
def vibrations(monkeypatch):
    """하드웨어로 나가는 진동 명령을 가로챈다(실제 기기 WS 는 테스트에 없다)."""
    from app.websocket import device_handler

    sent: list[dict] = []

    async def _spy(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(device_handler, "send_vibrate", _spy)
    return sent


@pytest.mark.asyncio
async def test_ondevice_detection_is_saved_but_does_not_vibrate_again(api_client, vibrations):
    """넥밴드는 이미 울렸다. 백엔드가 진동 명령을 또 보내면 같은 소리에 두 번 울린다."""
    client, session_factory = api_client
    await _seed(session_factory)
    await _make_active_mode_with_siren(client, session_factory)
    url = f"/devices/{THE_DEVICE_ID}/detections"

    r = await client.post(url, headers=_auth("ai-server"), json=_ondevice_detection(MATCHED))
    assert r.status_code == 200, r.text
    assert vibrations == []

    # 같은 소리라도 백엔드가 판단한 감지는 종전대로 진동 명령이 나간다.
    await client.post(url, headers=_auth("ai-server"), json=_detection(MATCHED))
    assert [v["sound_name"] for v in vibrations] == [MATCHED]

    items = (await client.get("/notifications", headers=_auth())).json()["items"]
    assert [item["sound_name"] for item in items] == [MATCHED, MATCHED]  # 기록은 둘 다 남는다


@pytest.mark.asyncio
async def test_ondevice_detection_outside_mode_is_still_recorded(api_client, vibrations):
    """실기기 테스트(10/3): 넥밴드는 모드를 모르고 긴급이면 진동한다. 백엔드가 모드 밖이라고 버리면
    사용자는 진동만 받고 앱에 기록이 없어 무슨 소리였는지 모른다 → 긴급 알림 ON 이면 기록을 남긴다."""
    client, session_factory = api_client
    await _seed(session_factory)
    await _make_active_mode_with_siren(client, session_factory)  # 경보음은 모드에 없다

    r = await client.post(
        f"/devices/{THE_DEVICE_ID}/detections",
        headers=_auth("ai-server"),
        json=_ondevice_detection(UNMATCHED_EMERGENCY),
    )
    assert r.status_code == 200, r.text

    items = (await client.get("/notifications", headers=_auth())).json()["items"]
    assert [item["sound_name"] for item in items] == [UNMATCHED_EMERGENCY]
    assert vibrations == []  # 이미 울렸으니 진동 명령은 여전히 생략


# --- 긴급 소리 알림 받기(emergency_alert_enabled)의 모드 필터 우회 -----------------------
# 토글이 켜져 있으면 긴급 카테고리는 활성 모드에 없어도(모드가 아예 없어도) 알림이 간다.
# 온디바이스가 안 다루는 긴급 소리도 똑같이 — "긴급은 다 온다"가 토글의 뜻이다.


@pytest.mark.asyncio
async def test_emergency_bypasses_mode_filter_and_vibrates(api_client, vibrations):
    """백엔드가 판단한(ondevice_vibrated 없음) 모드 밖 긴급 소리는 저장 + 진동 명령까지 나간다."""
    client, session_factory = api_client
    await _seed(session_factory)
    await _make_active_mode_with_siren(client, session_factory)

    r = await client.post(
        f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(UNMATCHED_EMERGENCY)
    )
    assert r.status_code == 200, r.text

    items = (await client.get("/notifications", headers=_auth())).json()["items"]
    assert [item["sound_name"] for item in items] == [UNMATCHED_EMERGENCY]
    assert [v["sound_name"] for v in vibrations] == [UNMATCHED_EMERGENCY]


@pytest.mark.asyncio
async def test_emergency_bypass_works_without_any_active_mode(api_client, vibrations):
    """활성 모드가 하나도 없어도 긴급 소리는 알림이 가야 한다(None 분기도 우회 안쪽)."""
    client, session_factory = api_client
    await _seed(session_factory)  # 모드를 만들지 않는다

    r = await client.post(
        f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(MATCHED)
    )
    assert r.status_code == 200, r.text

    items = (await client.get("/notifications", headers=_auth())).json()["items"]
    assert [item["sound_name"] for item in items] == [MATCHED]
    assert [v["sound_name"] for v in vibrations] == [MATCHED]


@pytest.mark.asyncio
async def test_emergency_bypass_does_not_cover_other_categories(api_client, vibrations):
    """우회는 긴급 카테고리만 — 생활음은 토글이 켜져 있어도 모드 필터를 그대로 탄다."""
    client, session_factory = api_client
    await _seed(session_factory)
    await _make_active_mode_with_siren(client, session_factory)

    r = await client.post(
        f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(*UNMATCHED_DAILY)
    )
    assert r.status_code == 200, r.text

    assert (await client.get("/notifications", headers=_auth())).json()["items"] == []
    assert vibrations == []


@pytest.mark.asyncio
async def test_emergency_toggle_off_restores_mode_filter(api_client, vibrations):
    """토글 OFF 면 긴급도 다른 소리처럼 활성 모드에 있어야 알림이 간다."""
    client, session_factory = api_client
    await _seed(session_factory, emergency_alert_enabled=False)
    await _make_active_mode_with_siren(client, session_factory)
    url = f"/devices/{THE_DEVICE_ID}/detections"

    r = await client.post(url, headers=_auth("ai-server"), json=_detection(UNMATCHED_EMERGENCY))
    assert r.status_code == 200, r.text
    r = await client.post(url, headers=_auth("ai-server"), json=_detection(MATCHED))
    assert r.status_code == 200, r.text

    items = (await client.get("/notifications", headers=_auth())).json()["items"]
    assert [item["sound_name"] for item in items] == [MATCHED]
    assert [v["sound_name"] for v in vibrations] == [MATCHED]


@pytest.mark.asyncio
async def test_do_not_disturb_beats_emergency_bypass(api_client, vibrations):
    """방해금지의 '완전 차단'은 긴급 우회보다 앞선다."""
    client, session_factory = api_client
    await _seed(session_factory, do_not_disturb=True)

    r = await client.post(
        f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_detection(MATCHED)
    )
    assert r.status_code == 200, r.text

    assert (await client.get("/notifications", headers=_auth())).json()["items"] == []
    assert vibrations == []


@pytest.mark.asyncio
async def test_do_not_disturb_still_suppresses_ondevice_detection(api_client, vibrations):
    """넥밴드가 방해금지를 모르고 진동한 경우(백엔드 소켓이 끊긴 동안 앱에서 켬)에도
    방해금지의 '완전 차단'이 우선한다."""
    client, session_factory = api_client
    await _seed(session_factory, do_not_disturb=True)
    await _make_active_mode_with_siren(client, session_factory)

    r = await client.post(
        f"/devices/{THE_DEVICE_ID}/detections", headers=_auth("ai-server"), json=_ondevice_detection(MATCHED)
    )
    assert r.status_code == 200, r.text

    assert (await client.get("/notifications", headers=_auth())).json()["items"] == []
    assert vibrations == []


@pytest.mark.asyncio
async def test_detection_with_explicit_false_flag_vibrates_as_before(api_client, vibrations):
    """AI 서버는 true/false 를 항상 보낸다 — false 는 필드가 없을 때와 같아야 한다."""
    client, session_factory = api_client
    await _seed(session_factory)
    await _make_active_mode_with_siren(client, session_factory)

    await client.post(
        f"/devices/{THE_DEVICE_ID}/detections",
        headers=_auth("ai-server"),
        json={**_detection(MATCHED), "ondevice_vibrated": False},
    )

    assert [v["sound_name"] for v in vibrations] == [MATCHED]
