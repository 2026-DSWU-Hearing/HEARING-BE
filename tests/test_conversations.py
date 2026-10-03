"""대화(양방향 소통) API 엔드투엔드 — 실 PostgreSQL 관통.

FE 계약(HEARING-FE src/pages/communication/apis/conversationApi.ts, types/conversationApiTypes.ts)
의 경로·필드명·상태코드를 그대로 검증한다. 필드명이 하나라도 어긋나면 FE 화면은 에러 없이 빈 값을 본다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.models.conversation import Conversation, ConversationBubble
from app.models.user import User
from app.schemas.conversation import BubbleIn
from app.services.conversation_service import (
    delete_stale_unended_conversations,
    make_summary,
    make_title,
)

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


async def _create_ended(client, *, user_id=USER_ID, **kwargs) -> int:
    """목록/상세엔 종료된 대화만 나온다 — 기록을 보는 테스트는 이걸로 만든다."""
    conversation_id = await _create(client, user_id=user_id, **kwargs)
    response = await client.post(f"{BASE}/{conversation_id}/end", json={"bubbles": BUBBLES}, headers=_auth(user_id))
    assert response.status_code == 200, response.text
    return conversation_id


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

    conversation_id = await _create_ended(client, latitude=None, longitude=None)

    detail = await client.get(f"{BASE}/{conversation_id}", headers=_auth())
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
    ids = [await _create_ended(client) for _ in range(5)]
    await _create_ended(client, user_id=OTHER_USER_ID)  # 남의 대화는 섞이면 안 된다

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


@pytest.mark.asyncio
async def test_list_and_detail_exclude_unended_conversations(api_client):
    """미종료 대화(ended_at null)는 기록이 아니다 — 목록·total 에서 빠지고 상세는 404.
    total 까지 빼야 FE 무한 스크롤의 has_next·페이지 크기가 맞는다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    ended_ids = [await _create_ended(client) for _ in range(2)]
    unended_id = await _create(client)  # 가장 최근이지만 첫 페이지에 끼면 안 된다

    first = (await client.get(BASE, params={"page": 1, "limit": 2}, headers=_auth())).json()
    assert first["total"] == 2 and first["has_next"] is False
    assert [c["conversation_id"] for c in first["conversations"]] == ended_ids[::-1]
    assert all(c["ended_at"] is not None for c in first["conversations"])
    assert (await client.get(f"{BASE}/{unended_id}", headers=_auth())).status_code == 404


@pytest.mark.asyncio
async def test_unended_conversation_can_still_be_ended_or_deleted(api_client):
    """상세 404 는 기록 화면 얘기일 뿐 — 진행 중인 대화의 end 와 빈 대화 DELETE 는 그대로 돼야 한다."""
    client, session_factory = api_client
    await _seed_users(session_factory)
    to_end = await _create(client)
    to_delete = await _create(client)

    assert (
        await client.post(f"{BASE}/{to_end}/end", json={"bubbles": BUBBLES}, headers=_auth())
    ).status_code == 200
    assert (await client.get(f"{BASE}/{to_end}", headers=_auth())).status_code == 200
    assert (await client.delete(f"{BASE}/{to_delete}", headers=_auth())).status_code == 200
    async with session_factory() as db:
        assert await db.get(Conversation, to_delete) is None


# --- 소유·삭제 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_users_conversation_is_404_everywhere(api_client):
    client, session_factory = api_client
    await _seed_users(session_factory)
    conversation_id = await _create_ended(client, user_id=OTHER_USER_ID)

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


# --- 미종료 대화 정리 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_deletes_only_stale_unended_conversations(api_client):
    """TTL 지난 미종료 대화만 지운다 — 종료된 대화는 오래돼도, 미종료라도 최근 것(진행 중)은 남긴다."""
    _, session_factory = api_client
    await _seed_users(session_factory)
    now = datetime.now(timezone.utc)
    stale = now - timedelta(hours=settings.CONVERSATION_UNENDED_TTL_HOURS, minutes=1)
    fresh = now - timedelta(hours=settings.CONVERSATION_UNENDED_TTL_HOURS, minutes=-1)
    async with session_factory() as db:
        stale_unended = Conversation(user_id=USER_ID, started_at=stale)
        stale_ended = Conversation(user_id=USER_ID, started_at=stale, ended_at=stale + timedelta(minutes=5))
        fresh_unended = Conversation(user_id=USER_ID, started_at=fresh)
        other_users_stale_unended = Conversation(user_id=OTHER_USER_ID, started_at=stale)
        db.add_all([stale_unended, stale_ended, fresh_unended, other_users_stale_unended])
        await db.flush()
        db.add(ConversationBubble(conversation_id=stale_unended.id, seq=0, direction="left", input_type="stt", content="x"))
        await db.commit()
        removed_ids = {stale_unended.id, other_users_stale_unended.id}
        kept_ids = {stale_ended.id, fresh_unended.id}

    async with session_factory() as db:
        assert await delete_stale_unended_conversations(db) == 2

    async with session_factory() as db:
        remaining = set((await db.execute(select(Conversation.id))).scalars().all())
        bubbles = (await db.execute(select(ConversationBubble.id))).scalars().all()
    assert remaining == kept_ids and not (remaining & removed_ids)
    assert bubbles == []  # 지운 대화의 버블은 FK CASCADE


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
