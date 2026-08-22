"""알림 목록(커서 페이지네이션)·일괄 삭제 엔드투엔드 통합테스트 — 실 PostgreSQL 관통.

여기서 검증하는 것들은 전부 **조용히** 깨지는 종류다. 커서를 잘못 자르면 에러 없이 알림이
누락되거나 무한 중복되고, 응답 스키마가 WS 와 어긋나면 FE 목록이 통째로 빈 화면이 된다.
그래서 단위테스트가 아니라 실제 앱·실제 DB 를 관통해서 확인한다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import create_access_token
from app.models.notification import Notification
from app.models.user import User

USER_ID = 1
OTHER_USER_ID = 2

_BASE_TIME = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def _auth(user_id: int = USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, source='user')}"}


def _notification(user_id: int, index: int, *, detected_at: datetime) -> Notification:
    return Notification(
        user_id=user_id,
        device_id=None,
        sound_id=None,
        sound_name=f"사이렌{index}",
        sound_category="긴급",
        source="ai-server",
        confidence=0.9,
        location=None,
        detected_at=detected_at,
        is_read=False,
    )


async def _seed_users(session_factory) -> None:
    async with session_factory() as db:
        db.add(User(id=USER_ID, email="u@t.local", nickname="u", terms_agreed=True))
        db.add(User(id=OTHER_USER_ID, email="o@t.local", nickname="o", terms_agreed=True))
        await db.commit()


async def _seed_notifications(session_factory, user_id: int, count: int, *, same_second: bool = False):
    """최신순으로 count 건. same_second=True 면 detected_at 이 전부 동일하다
    (넥밴드가 같은 초에 여러 소리를 감지하는 실제 상황)."""
    async with session_factory() as db:
        for i in range(count):
            detected_at = _BASE_TIME if same_second else _BASE_TIME - timedelta(minutes=i)
            db.add(_notification(user_id, i, detected_at=detected_at))
        await db.commit()


async def _drain(client, *, limit: int) -> list[dict]:
    """커서를 끝까지 따라가며 전 페이지를 모은다."""
    collected: list[dict] = []
    cursor: str | None = None
    for _ in range(20):  # 무한 루프 방어 — 정상이면 훨씬 빨리 끝난다
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = await client.get("/notifications", headers=_auth(), params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        collected.extend(body["items"])
        if not body["has_next"]:
            assert body["next_cursor"] is None
            return collected
        cursor = body["next_cursor"]
        assert cursor is not None
    raise AssertionError("커서가 끝나지 않았다 — 페이지네이션이 제자리를 돈다")


@pytest.mark.asyncio
async def test_list_is_newest_first_and_only_mine(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 3)
    await _seed_notifications(session_factory, OTHER_USER_ID, 5)

    response = await client.get("/notifications", headers=_auth())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["has_next"] is False and body["next_cursor"] is None
    assert [item["sound_name"] for item in body["items"]] == ["사이렌0", "사이렌1", "사이렌2"]


@pytest.mark.asyncio
async def test_item_schema_matches_websocket_payload(api_client):
    """FE 는 WS 이벤트를 이 목록 캐시에 그대로 끼워 넣는다. 필드가 하나라도 다르면
    같은 알림이 두 번 보이거나 낙관적 삽입 항목의 id 가 서버와 안 맞는다."""
    from app.schemas.notification import NotificationItem

    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 1)

    response = await client.get("/notifications", headers=_auth())
    item = response.json()["items"][0]

    assert set(item) == set(NotificationItem.model_fields)
    # confidence 가 널이면 FE 는 이 페이지 전체를 무효로 보고 목록을 비운다.
    assert isinstance(item["confidence"], float)
    # 오프셋 없는 시각은 브라우저가 UTC 로도 로컬로도 해석해 9시간 어긋난다.
    assert datetime.fromisoformat(item["detected_at"]).tzinfo is not None


@pytest.mark.asyncio
async def test_cursor_walks_every_item_exactly_once(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 7)

    collected = await _drain(client, limit=3)

    ids = [item["id"] for item in collected]
    assert len(ids) == 7, "페이지 사이에서 항목이 누락됐다"
    assert len(set(ids)) == 7, "페이지 사이에서 항목이 중복됐다"


@pytest.mark.asyncio
async def test_cursor_handles_identical_detected_at(api_client):
    """detected_at 단독 커서였다면 여기서 동점 그룹이 통째로 누락되거나 무한 중복된다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 6, same_second=True)

    collected = await _drain(client, limit=2)

    ids = [item["id"] for item in collected]
    assert len(ids) == 6 and len(set(ids)) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -5, 999])
async def test_out_of_range_limit_is_clamped_not_rejected(api_client, limit):
    """400 을 주면 무한 스크롤 도중 화면이 이유 없이 멈춘다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 3)

    response = await client.get("/notifications", headers=_auth(), params={"limit": limit})
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["not-base64!!", "", "bm90LWEtY3Vyc29y"])
async def test_broken_cursor_returns_422(api_client, cursor):
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 2)

    response = await client.get("/notifications", headers=_auth(), params={"cursor": cursor})
    # 빈 커서는 '커서 없음'과 같게 취급된다(falsy) — 그 경우만 200.
    expected = 200 if cursor == "" else 422
    assert response.status_code == expected, response.text


@pytest.mark.asyncio
async def test_delete_is_idempotent_and_scoped_to_me(api_client):
    """없는 id·남의 id 가 섞여도 404·403 을 내지 않고 내 것만 지운다.
    403 을 주면 남의 알림 id 존재 여부가 새어 나간다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 2)
    await _seed_notifications(session_factory, OTHER_USER_ID, 2)

    mine = [item["id"] for item in (await client.get("/notifications", headers=_auth())).json()["items"]]
    others = [
        item["id"]
        for item in (await client.get("/notifications", headers=_auth(OTHER_USER_ID))).json()["items"]
    ]

    response = await client.post(
        "/notifications/delete", headers=_auth(), json={"ids": mine + others + [999999]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["deleted_count"] == len(mine)

    # 같은 요청을 다시 보내도 성공한다(네트워크 타임아웃 후 재시도가 안전해야 한다).
    again = await client.post(
        "/notifications/delete", headers=_auth(), json={"ids": mine + others + [999999]}
    )
    assert again.status_code == 200 and again.json()["deleted_count"] == 0

    # 같은 기기를 쓰는 다른 계정의 목록은 전혀 변하지 않는다.
    still = (await client.get("/notifications", headers=_auth(OTHER_USER_ID))).json()
    assert [item["id"] for item in still["items"]] == others


@pytest.mark.asyncio
async def test_delete_dedupes_ids(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 1)

    target = (await client.get("/notifications", headers=_auth())).json()["items"][0]["id"]

    response = await client.post(
        "/notifications/delete", headers=_auth(), json={"ids": [target, target, target]}
    )
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[], list(range(101))])
async def test_delete_rejects_out_of_range_id_count(api_client, ids):
    client, session_factory = api_client
    await _seed_users(session_factory)

    response = await client.post("/notifications/delete", headers=_auth(), json={"ids": ids})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_delete_all_clears_only_my_notifications(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _seed_notifications(session_factory, USER_ID, 4)
    await _seed_notifications(session_factory, OTHER_USER_ID, 3)

    response = await client.post("/notifications/delete-all", headers=_auth())
    assert response.status_code == 200, response.text
    assert response.json()["deleted_count"] == 4

    assert (await client.get("/notifications", headers=_auth())).json()["items"] == []
    assert len((await client.get("/notifications", headers=_auth(OTHER_USER_ID))).json()["items"]) == 3
