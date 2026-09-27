from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.quick_reply import QuickReply


async def list_replies(db: AsyncSession, user_id: int) -> list[QuickReply]:
    # 만든 순서대로 — 사용자가 위에 추가한 걸 위에서 보는 게 자연스럽고 별도 정렬 UI 가 없다.
    result = await db.execute(
        select(QuickReply).where(QuickReply.user_id == user_id).order_by(QuickReply.id)
    )
    return list(result.scalars().all())


async def create_reply(db: AsyncSession, user_id: int, content: str) -> QuickReply:
    reply = QuickReply(user_id=user_id, content=content)
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    return reply


async def update_reply(db: AsyncSession, user_id: int, reply_id: int, content: str) -> QuickReply:
    reply = await _get_owned(db, user_id, reply_id)
    reply.content = content
    await db.commit()
    await db.refresh(reply)
    return reply


async def delete_reply(db: AsyncSession, user_id: int, reply_id: int) -> None:
    reply = await _get_owned(db, user_id, reply_id)
    await db.delete(reply)
    await db.commit()


async def _get_owned(db: AsyncSession, user_id: int, reply_id: int) -> QuickReply:
    """남의 문구는 404 — 순차 id 라 존재 여부를 흘리지 않는다(대화와 같은 정책)."""
    result = await db.execute(
        select(QuickReply).where(QuickReply.id == reply_id, QuickReply.user_id == user_id)
    )
    reply = result.scalar_one_or_none()
    if reply is None:
        raise NotFoundException("Quick reply not found")
    return reply
