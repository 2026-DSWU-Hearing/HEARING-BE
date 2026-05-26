from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.db.functions import apply_pagination, get_or_404
from app.models.conversation import Conversation, ConversationBubble
from app.schemas.conversation import BubbleCreate, ConversationCreate
from app.services import location_service


async def list_conversations(db: AsyncSession, user_id: int, page: int = 1, size: int = 30) -> list[Conversation]:
    q = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.started_at.desc())
    )
    result = await db.execute(apply_pagination(q, page, size))
    return list(result.scalars().all())


async def create_conversation(db: AsyncSession, user_id: int, payload: ConversationCreate) -> Conversation:
    location = None
    if payload.latitude is not None and payload.longitude is not None:
        location = await location_service.reverse_geocode(payload.latitude, payload.longitude)
    conv = Conversation(
        user_id=user_id,
        title=payload.title,
        location=location,
        started_at=datetime.now(timezone.utc),
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def get_conversation(db: AsyncSession, user_id: int, conv_id: int) -> Conversation:
    conv = await get_or_404(db, Conversation, conv_id)
    if conv.user_id != user_id:
        raise ForbiddenException("Not your conversation")
    return conv


async def end_conversation(db: AsyncSession, user_id: int, conv_id: int) -> Conversation:
    conv = await get_conversation(db, user_id, conv_id)
    conv.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(conv)
    return conv


async def delete_conversation(db: AsyncSession, user_id: int, conv_id: int) -> None:
    conv = await get_conversation(db, user_id, conv_id)
    await db.delete(conv)
    await db.commit()


async def add_bubble(db: AsyncSession, user_id: int, conv_id: int, payload: BubbleCreate) -> ConversationBubble:
    conv = await get_conversation(db, user_id, conv_id)
    bubble = ConversationBubble(conversation_id=conv.id, speaker=payload.speaker, text=payload.text)
    db.add(bubble)
    await db.commit()
    await db.refresh(bubble)
    return bubble


async def list_bubbles(db: AsyncSession, user_id: int, conv_id: int) -> list[ConversationBubble]:
    conv = await get_conversation(db, user_id, conv_id)
    result = await db.execute(
        select(ConversationBubble)
        .where(ConversationBubble.conversation_id == conv.id)
        .order_by(ConversationBubble.created_at)
    )
    return list(result.scalars().all())
