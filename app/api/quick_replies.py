from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.quick_reply import QuickReplyCreate, QuickReplyResponse, QuickReplyUpdate
from app.services import quick_reply_service

router = APIRouter()


@router.get("", response_model=list[QuickReplyResponse])
async def list_replies(user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await quick_reply_service.list_replies(db, user_id)


@router.post("", response_model=QuickReplyResponse)
async def create_reply(payload: QuickReplyCreate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await quick_reply_service.create_reply(db, user_id, payload)


@router.patch("/{reply_id}", response_model=QuickReplyResponse)
async def update_reply(reply_id: int, payload: QuickReplyUpdate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await quick_reply_service.update_reply(db, user_id, reply_id, payload)


@router.delete("/{reply_id}")
async def delete_reply(reply_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await quick_reply_service.delete_reply(db, user_id, reply_id)
    return {"ok": True}
