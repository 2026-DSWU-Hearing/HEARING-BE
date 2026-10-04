"""모드 API 응답 계약 — 생성/수정/소리 교체 응답의 `sounds` 가 상세 조회와 같은 형태인지.

FE 버그리포트: PUT 응답에 `{sound_id, name}` 만 있어서 FE 가 is_active 를 이전 캐시로 추측했고,
그 추측이 틀려 화면이 갱신되지 않았다. 네 응답 모두 `{sound_id, name, category, is_active}` 를
내려주면 FE 는 응답을 그대로 캐시에 넣는다.
"""

import pytest

from app.core.security import create_access_token
from app.models.user import User

USER_ID = 1
SOUND_FIELDS = {"sound_id", "name", "category", "is_active"}


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER_ID, source='user')}"}


async def _seed_user(session_factory) -> None:
    async with session_factory() as db:
        db.add(User(id=USER_ID, email="u@t.local", nickname="u", terms_agreed=True))
        await db.commit()


def _active_map(body: dict) -> dict[int, bool]:
    return {s["sound_id"]: s["is_active"] for s in body["sounds"]}


@pytest.mark.asyncio
async def test_write_responses_carry_category_and_is_active(api_client):
    client, session_factory = api_client
    await _seed_user(session_factory)

    r = await client.post(
        "/modes", headers=_auth(), json={"name": "외출", "icon": "walk", "sounds": [{"sound_id": 1}, {"sound_id": 2}]}
    )
    assert r.status_code == 200, r.text
    mode_id = r.json()["mode_id"]
    assert all(set(s) == SOUND_FIELDS for s in r.json()["sounds"])
    assert _active_map(r.json()) == {1: True, 2: True}

    # 홈에서 소리 카드를 눌러 1 을 끈다
    r = await client.patch(f"/modes/{mode_id}/sounds/1", headers=_auth(), json={"is_active": False})
    assert r.status_code == 200, r.text

    # 이름만 고치고 소리 목록은 그대로 → 응답에 꺼짐이 그대로 보여야 FE 캐시가 맞는다
    r = await client.put(
        f"/modes/{mode_id}",
        headers=_auth(),
        json={"name": "산책", "icon": "walk", "sounds": [{"sound_id": 1}, {"sound_id": 2}]},
    )
    assert r.status_code == 200, r.text
    assert all(set(s) == SOUND_FIELDS for s in r.json()["sounds"])
    assert _active_map(r.json()) == {1: False, 2: True}

    # 소리 교체: 1 유지(꺼짐), 2 제거, 3 추가(켜짐)
    r = await client.put(f"/modes/{mode_id}/sounds", headers=_auth(), json={"sounds": [{"sound_id": 1}, {"sound_id": 3}]})
    assert r.status_code == 200, r.text
    assert all(set(s) == SOUND_FIELDS for s in r.json()["sounds"])
    assert _active_map(r.json()) == {1: False, 3: True}

    # 상세 조회와 같은 형태·같은 값
    detail = (await client.get(f"/modes/{mode_id}", headers=_auth())).json()
    assert detail["sounds"] == r.json()["sounds"]
    assert {s["category"] for s in detail["sounds"]} == {"긴급"}
