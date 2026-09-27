"""대화(양방향 소통) 서비스.

수명주기: create(마이크 켜기 전) → [STT 소켓이 conversation_id 로 붙음] → end(버블 일괄 저장 +
제목/요약) 또는 delete(빈 대화). 버블 단건 저장 API 는 없다 — 화면 상태는 FE 가 들고 있다가
종료 때 통째로 올린다(FE useActiveConversationStore 의 결정).
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, NotFoundException
from app.models.conversation import Conversation, ConversationBubble
from app.schemas.conversation import BubbleIn, ConversationCreate

LIST_LIMIT_DEFAULT = 20
LIST_LIMIT_MAX = 100

TITLE_MAX_CHARS = 30
SUMMARY_MAX_CHARS = 120


async def create_conversation(db: AsyncSession, user_id: int, payload: ConversationCreate) -> Conversation:
    conversation = Conversation(
        user_id=user_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        started_at=datetime.now(timezone.utc),
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_owned_conversation(db: AsyncSession, user_id: int, conversation_id: int) -> Conversation:
    """남의 대화는 403 이 아니라 404 — 대화 id 는 순차 정수라 존재 여부 자체를 흘리지 않는다."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise NotFoundException("Conversation not found")
    return conversation


async def get_conversation_detail(db: AsyncSession, user_id: int, conversation_id: int) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.bubbles))
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise NotFoundException("Conversation not found")
    return conversation


async def list_conversations(
    db: AsyncSession, user_id: int, page: int, limit: int
) -> tuple[list[Conversation], int, int, int]:
    """(items, total, page, limit). 범위 밖 page/limit 은 400 대신 잘라낸다 — 무한 스크롤 도중
    400 이 나면 화면이 이유 없이 멈춘다(알림 목록과 같은 정책)."""
    page = max(page, 1)
    limit = min(max(limit, 1), LIST_LIMIT_MAX)

    total = await db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    )
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.started_at.desc(), Conversation.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total or 0), page, limit


async def end_conversation(
    db: AsyncSession, user_id: int, conversation_id: int, bubbles: list[BubbleIn]
) -> Conversation:
    """버블 일괄 저장 + 종료 시각 + 제목/요약. 두 번 끝내면 409 — FE 는 end 후 세션을 비우므로
    정상 흐름에선 안 오고, 오면 재시도가 버블을 두 배로 붙이는 사고이니 막는다."""
    conversation = await get_owned_conversation(db, user_id, conversation_id)
    if conversation.ended_at is not None:
        raise ConflictException("Conversation already ended", code="ALREADY_ENDED")

    for seq, bubble in enumerate(bubbles):
        db.add(
            ConversationBubble(
                conversation_id=conversation.id,
                seq=seq,
                direction=bubble.direction,
                input_type=bubble.input_type,
                content=bubble.content,
            )
        )
    conversation.title = make_title(bubbles)
    conversation.summary = make_summary(bubbles)
    conversation.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(db: AsyncSession, user_id: int, conversation_id: int) -> None:
    conversation = await get_owned_conversation(db, user_id, conversation_id)
    await db.delete(conversation)  # 버블은 FK CASCADE
    await db.commit()


# --- 제목/요약 (휴리스틱) --------------------------------------------------------
# LLM 없이 버블 텍스트만으로 만든다. 나중에 AI 요약으로 바꾸려면 이 두 함수만 교체하면 된다
# (end_conversation 과 응답 계약은 그대로).


def make_title(bubbles: list[BubbleIn]) -> str:
    """첫 버블의 첫 문장. FE 로컬 기록도 '첫 마디'를 제목으로 쓰므로 화면이 서버/로컬 간에 일치한다."""
    first = _first_sentence(bubbles[0].content)
    return _truncate(first, TITLE_MAX_CHARS)


def make_summary(bubbles: list[BubbleIn]) -> str:
    """버블을 순서대로 이어 붙여 앞부분만. 화자 구분은 '/'로 — 목록 미리보기 한 줄이 목적이다."""
    joined = " / ".join(_squash_whitespace(bubble.content) for bubble in bubbles)
    return _truncate(joined, SUMMARY_MAX_CHARS)


def _first_sentence(text: str) -> str:
    text = _squash_whitespace(text)
    for i, ch in enumerate(text):
        if ch in ".?!。":
            return text[: i + 1]
    return text


def _squash_whitespace(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
