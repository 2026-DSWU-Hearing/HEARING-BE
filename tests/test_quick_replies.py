"""자주 쓰는 답변 CRUD — FE 계약(quickReplyApi.ts / quickReplyApiTypes.ts) 그대로."""

import pytest

from app.core.security import create_access_token
from app.models.user import User

USER_ID = 1
OTHER_USER_ID = 2
BASE = "/api/quick-replies"


def _auth(user_id: int = USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, source='user')}"}


async def _seed_users(session_factory) -> None:
    async with session_factory() as db:
        db.add(User(id=USER_ID, email="u@t.local", nickname="u", terms_agreed=True))
        db.add(User(id=OTHER_USER_ID, email="o@t.local", nickname="o", terms_agreed=True))
        await db.commit()


@pytest.mark.asyncio
async def test_crud_round_trip(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)

    created = await client.post(BASE, json={"content": "  천천히 말씀해 주세요  "}, headers=_auth())
    assert created.status_code == 201, created.text
    assert set(created.json()) == {"reply_id", "content", "created_at"}
    assert created.json()["content"] == "천천히 말씀해 주세요"  # trim 저장
    reply_id = created.json()["reply_id"]

    second = (await client.post(BASE, json={"content": "글로 적어주시겠어요?"}, headers=_auth())).json()

    listed = (await client.get(BASE, headers=_auth())).json()
    assert [r["content"] for r in listed["quick_replies"]] == ["천천히 말씀해 주세요", "글로 적어주시겠어요?"]
    assert set(listed["quick_replies"][0]) == {"reply_id", "content"}

    updated = await client.put(f"{BASE}/{reply_id}", json={"content": "조금만 천천히요"}, headers=_auth())
    assert updated.status_code == 200
    assert updated.json() == {"reply_id": reply_id, "content": "조금만 천천히요"}

    assert (await client.delete(f"{BASE}/{reply_id}", headers=_auth())).status_code == 200
    remaining = (await client.get(BASE, headers=_auth())).json()["quick_replies"]
    assert [r["reply_id"] for r in remaining] == [second["reply_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "   ", "가" * 201])
async def test_rejects_blank_or_too_long_content(api_client, content):
    client, session_factory = api_client
    await _seed_users(session_factory)

    assert (await client.post(BASE, json={"content": content}, headers=_auth())).status_code == 422


@pytest.mark.asyncio
async def test_other_users_reply_is_404(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    reply_id = (await client.post(BASE, json={"content": "남의 것"}, headers=_auth(OTHER_USER_ID))).json()["reply_id"]

    assert (await client.put(f"{BASE}/{reply_id}", json={"content": "x"}, headers=_auth())).status_code == 404
    assert (await client.delete(f"{BASE}/{reply_id}", headers=_auth())).status_code == 404
    assert (await client.get(BASE, headers=_auth())).json()["quick_replies"] == []
    assert len((await client.get(BASE, headers=_auth(OTHER_USER_ID))).json()["quick_replies"]) == 1
