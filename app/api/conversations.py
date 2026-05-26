from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.conversation import BubbleCreate, BubbleResponse, ConversationCreate, ConversationResponse
from app.services import conversation_service

router = APIRouter()


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await conversation_service.list_conversations(db, user_id, page, size)


@router.post("", response_model=ConversationResponse)
async def create_conversation(payload: ConversationCreate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await conversation_service.create_conversation(db, user_id, payload)


@router.get("/{conv_id}", response_model=ConversationResponse)
async def get_conversation(conv_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await conversation_service.get_conversation(db, user_id, conv_id)


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await conversation_service.delete_conversation(db, user_id, conv_id)
    return {"ok": True}


@router.post("/{conv_id}/end", response_model=ConversationResponse)
async def end_conversation(conv_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await conversation_service.end_conversation(db, user_id, conv_id)


@router.get("/{conv_id}/bubbles", response_model=list[BubbleResponse])
async def list_bubbles(conv_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await conversation_service.list_bubbles(db, user_id, conv_id)


@router.post("/{conv_id}/bubbles", response_model=BubbleResponse)
async def add_bubble(conv_id: int, payload: BubbleCreate, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await conversation_service.add_bubble(db, user_id, conv_id, payload)
