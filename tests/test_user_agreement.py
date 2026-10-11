"""PATCH /users/me/agreement 부분 갱신 + GET /users/me 노출.

동의 여부의 정본은 서버다. FE 는 localStorage 대신 /users/me 에서 읽는다.
"""

import pytest

from app.core.security import create_access_token
from app.models.user import User

USER_ID = 1


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER_ID, source='user')}"}


async def _seed(session_factory) -> None:
    async with session_factory() as db:
        db.add(User(id=USER_ID, email="u@t.local", nickname="u", terms_agreed=True))
        await db.commit()


@pytest.mark.asyncio
async def test_location_agreed_defaults_false_and_partial_patch_keeps_terms(api_client):
    client, session_factory = api_client
    await _seed(session_factory)

    me = (await client.get("/users/me", headers=_auth())).json()
    assert me["terms_agreed"] is True
    assert me["location_agreed"] is False

    # 모달은 location_agreed 만 보낸다 — terms_agreed 는 건드리지 않아야 한다.
    r = await client.patch("/users/me/agreement", headers=_auth(), json={"location_agreed": True})
    assert r.status_code == 200, r.text
    assert r.json()["location_agreed"] is True
    assert r.json()["terms_agreed"] is True

    me = (await client.get("/users/me", headers=_auth())).json()
    assert me["location_agreed"] is True


@pytest.mark.asyncio
async def test_agreement_patch_rejects_empty_body(api_client):
    client, session_factory = api_client
    await _seed(session_factory)

    r = await client.patch("/users/me/agreement", headers=_auth(), json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_sends_both_flags_together(api_client):
    client, session_factory = api_client
    await _seed(session_factory)

    r = await client.patch(
        "/users/me/agreement", headers=_auth(), json={"terms_agreed": True, "location_agreed": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["terms_agreed"] is True
    assert r.json()["location_agreed"] is True
