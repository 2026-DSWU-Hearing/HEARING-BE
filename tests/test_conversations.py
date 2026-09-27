"""대화(양방향 소통) API 엔드투엔드 — 실 PostgreSQL 관통.

FE 계약(HEARING-FE src/pages/communication/apis/conversationApi.ts, types/conversationApiTypes.ts)
의 경로·필드명·상태코드를 그대로 검증한다. 필드명이 하나라도 어긋나면 FE 화면은 에러 없이 빈 값을 본다.
"""

import pytest

from app.core.security import create_access_token
from app.models.user import User
from app.schemas.conversation import BubbleIn
from app.services.conversation_service import make_summary, make_title

USER_ID = 1
OTHER_USER_ID = 2
BASE = "/api/conversations"


def _auth(user_id: int = USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, source='user')}"}


async def _seed_users(session_factory) -> None:
    async with session_factory() as db:
        db.add(User(id=USER_ID, email="u@t.local", nickname="u", terms_agreed=True))
        db.add(User(id=OTHER_USER_ID, email="o@t.local", nickname="o", terms_agreed=True))
        await db.commit()


async def _create(client, *, latitude=37.5, longitude=127.0, user_id=USER_ID) -> int:
    response = await client.post(BASE, json={"latitude": latitude, "longitude": longitude}, headers=_auth(user_id))
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


BUBBLES = [
    {"direction": "left", "inputType": "stt", "content": "안녕하세요. 주문 도와드릴까요?"},
    {"direction": "right", "inputType": "favorite_answer", "content": "네, 아메리카노 한 잔이요"},
    {"direction": "left", "inputType": "stt", "content": "따뜻한 걸로 드릴까요"},
]


# --- 생성 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_id_and_created_at(api_client):
    """FE 는 응답의 conversation_id 로 STT 소켓 주소를 만든다 — 이 이름이 정확해야 한다."""
    client, session_factory = api_client
    await _seed_users(session_factory)

    response = await client.post(BASE, json={"latitude": 37.5, "longitude": 127.0}, headers=_auth())

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"conversation_id", "created_at"}
    assert isinstance(body["conversation_id"], int)


@pytest.mark.asyncio
async def test_create_accepts_null_location(api_client):
    """위치 권한 거부·실내면 FE 가 null/null 을 보낸다 — 필수로 막으면 대화 시작부터 실패한다."""
    client, session_factory = api_client
    await _seed_users(session_factory)

    response = await client.post(BASE, json={"latitude": None, "longitude": None}, headers=_auth())

    assert response.status_code == 201
    detail = await client.get(f"{BASE}/{response.json()['conversation_id']}", headers=_auth())
    assert detail.json()["latitude"] is None and detail.json()["longitude"] is None


@pytest.mark.asyncio
async def test_create_rejects_out_of_range_coordinates(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)

    response = await client.post(BASE, json={"latitude": 91, "longitude": 0}, headers=_auth())

    assert response.status_code == 422


# --- 종료(일괄 저장) -------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_saves_bubbles_in_order_and_generates_title_summary(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    conversation_id = await _create(client)

    ended = await client.post(f"{BASE}/{conversation_id}/end", json={"bubbles": BUBBLES}, headers=_auth())

    assert ended.status_code == 200, ended.text
    body = ended.json()
    assert body["conversation_id"] == conversation_id
    assert body["title"] == "안녕하세요."
    assert body["summary"] == "안녕하세요. 주문 도와드릴까요? / 네, 아메리카노 한 잔이요 / 따뜻한 걸로 드릴까요"

    detail = (await client.get(f"{BASE}/{conversation_id}", headers=_auth())).json()
    assert detail["title"] == body["title"] and detail["summary"] == body["summary"]
    assert detail["ended_at"] is not None
    assert detail["latitude"] == 37.5 and detail["longitude"] == 127.0
    # 버블은 요청 배열 순서 그대로, FE 필드명(bubble_id, inputType, created_at)으로.
    assert [b["content"] for b in detail["bubbles"]] == [b["content"] for b in BUBBLES]
    assert [b["inputType"] for b in detail["bubbles"]] == ["stt", "favorite_answer", "stt"]
    assert [b["direction"] for b in detail["bubbles"]] == ["left", "right", "left"]
    assert all({"bubble_id", "created_at"} <= set(b) for b in detail["bubbles"])


@pytest.mark.asyncio
async def test_end_twice_is_conflict(api_client):
    """재시도가 버블을 두 배로 붙이지 않도록 두 번째 end 는 409."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    conversation_id = await _create(client)
    await client.post(f"{BASE}/{conversation_id}/end", json={"bubbles": BUBBLES}, headers=_auth())

    again = await client.post(f"{BASE}/{conversation_id}/end", json={"bubbles": BUBBLES}, headers=_auth())

    assert again.status_code == 409
    assert again.json()["code"] == "ALREADY_ENDED"
    detail = (await client.get(f"{BASE}/{conversation_id}", headers=_auth())).json()
    assert len(detail["bubbles"]) == len(BUBBLES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bubbles",
    [
        [],
        [{"direction": "left", "inputType": "stt", "content": "   "}],
        [{"direction": "up", "inputType": "stt", "content": "x"}],
        [{"direction": "left", "inputType": "voice", "content": "x"}],
    ],
)
async def test_end_rejects_invalid_bubbles(api_client, bubbles):
    client, session_factory = api_client
    await _seed_users(session_factory)
    conversation_id = await _create(client)

    response = await client.post(f"{BASE}/{conversation_id}/end", json={"bubbles": bubbles}, headers=_auth())

    assert response.status_code == 422


# --- 목록 ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_paginates_newest_first(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    ids = [await _create(client) for _ in range(5)]
    await _create(client, user_id=OTHER_USER_ID)  # 남의 대화는 섞이면 안 된다

    first = (await client.get(BASE, params={"page": 1, "limit": 2}, headers=_auth())).json()
    assert first["total"] == 5 and first["page"] == 1 and first["limit"] == 2 and first["has_next"] is True
    assert [c["conversation_id"] for c in first["conversations"]] == ids[::-1][:2]
    assert {"title", "summary", "latitude", "longitude", "ended_at", "created_at"} <= set(first["conversations"][0])

    last = (await client.get(BASE, params={"page": 3, "limit": 2}, headers=_auth())).json()
    assert [c["conversation_id"] for c in last["conversations"]] == [ids[0]]
    assert last["has_next"] is False


@pytest.mark.asyncio
async def test_list_clamps_out_of_range_paging_instead_of_400(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    await _create(client)

    response = await client.get(BASE, params={"page": 0, "limit": 9999}, headers=_auth())

    assert response.status_code == 200
    assert response.json()["page"] == 1 and response.json()["limit"] == 100


# --- 소유·삭제 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_users_conversation_is_404_everywhere(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    conversation_id = await _create(client, user_id=OTHER_USER_ID)

    assert (await client.get(f"{BASE}/{conversation_id}", headers=_auth())).status_code == 404
    assert (
        await client.post(f"{BASE}/{conversation_id}/end", json={"bubbles": BUBBLES}, headers=_auth())
    ).status_code == 404
    assert (await client.delete(f"{BASE}/{conversation_id}", headers=_auth())).status_code == 404
    # 남이 건드려도 원래 주인 대화는 멀쩡하다.
    assert (await client.get(f"{BASE}/{conversation_id}", headers=_auth(OTHER_USER_ID))).status_code == 200


@pytest.mark.asyncio
async def test_delete_removes_conversation_and_bubbles(api_client):
    """FE 는 버블 없이 마이크만 켰다 끈 경우 end 대신 DELETE 를 부른다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    conversation_id = await _create(client)
    await client.post(f"{BASE}/{conversation_id}/end", json={"bubbles": BUBBLES}, headers=_auth())

    assert (await client.delete(f"{BASE}/{conversation_id}", headers=_auth())).status_code == 200
    assert (await client.get(f"{BASE}/{conversation_id}", headers=_auth())).status_code == 404
    assert (await client.get(BASE, headers=_auth())).json()["total"] == 0


# --- 제목/요약 휴리스틱 -----------------------------------------------------------


def _bubble(content: str) -> BubbleIn:
    return BubbleIn(direction="left", inputType="stt", content=content)


def test_title_is_first_sentence_of_first_bubble():
    assert make_title([_bubble("주문 도와드릴까요? 메뉴 보시죠"), _bubble("네")]) == "주문 도와드릴까요?"


def test_title_truncates_long_first_bubble_with_ellipsis():
    title = make_title([_bubble("가" * 80)])

    assert len(title) == 30 and title.endswith("…")


def test_summary_joins_bubbles_and_squashes_whitespace():
    assert make_summary([_bubble("안녕  하세요\n반갑습니다"), _bubble("네")]) == "안녕 하세요 반갑습니다 / 네"


def test_summary_truncates():
    summary = make_summary([_bubble("가" * 200)])

    assert len(summary) == 120 and summary.endswith("…")
