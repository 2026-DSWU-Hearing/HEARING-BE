from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.db.functions import get_or_404
from app.models.quick_reply import QuickReply
from app.schemas.quick_reply import QuickReplyCreate, QuickReplyUpdate


async def list_replies(db: AsyncSession, user_id: int) -> list[QuickReply]:
    result = await db.execute(
        select(QuickReply).where(QuickReply.user_id == user_id).order_by(QuickReply.order)
    )
    return list(result.scalars().all())


async def create_reply(db: AsyncSession, user_id: int, payload: QuickReplyCreate) -> QuickReply:
    reply = QuickReply(user_id=user_id, text=payload.text, order=payload.order)
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    return reply


async def update_reply(db: AsyncSession, user_id: int, reply_id: int, payload: QuickReplyUpdate) -> QuickReply:
    reply = await _get_owned(db, user_id, reply_id)
    if payload.text is not None:
        reply.text = payload.text
    if payload.order is not None:
        reply.order = payload.order
    await db.commit()
    await db.refresh(reply)
    return reply


async def delete_reply(db: AsyncSession, user_id: int, reply_id: int) -> None:
    reply = await _get_owned(db, user_id, reply_id)
    await db.delete(reply)
    await db.commit()


async def _get_owned(db: AsyncSession, user_id: int, reply_id: int) -> QuickReply:
    reply = await get_or_404(db, QuickReply, reply_id)
    if reply.user_id != user_id:
        raise ForbiddenException("Not your quick reply")
    return reply
