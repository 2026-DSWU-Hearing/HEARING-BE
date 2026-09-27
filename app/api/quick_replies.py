from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.quick_reply import QuickReplyCreated, QuickReplyListResponse, QuickReplyOut, QuickReplyWrite
from app.services import quick_reply_service

router = APIRouter()


@router.get("", response_model=QuickReplyListResponse)
async def list_replies(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    replies = await quick_reply_service.list_replies(db, user_id)
    return QuickReplyListResponse(quick_replies=[QuickReplyOut.model_validate(r) for r in replies])


@router.post("", response_model=QuickReplyCreated, status_code=201)
async def create_reply(
    payload: QuickReplyWrite,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await quick_reply_service.create_reply(db, user_id, payload.content)


@router.put("/{reply_id}", response_model=QuickReplyOut)
async def update_reply(
    reply_id: int,
    payload: QuickReplyWrite,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await quick_reply_service.update_reply(db, user_id, reply_id, payload.content)


@router.delete("/{reply_id}")
async def delete_reply(
    reply_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await quick_reply_service.delete_reply(db, user_id, reply_id)
    return {"ok": True}
