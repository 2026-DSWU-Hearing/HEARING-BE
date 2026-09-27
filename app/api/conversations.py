from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.conversation import (
    ConversationCreate,
    ConversationCreated,
    ConversationDetail,
    ConversationEnded,
    ConversationEndRequest,
    ConversationListItem,
    ConversationListResponse,
)
from app.services import conversation_service

router = APIRouter()


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    page: int = Query(1),
    limit: int = Query(conversation_service.LIST_LIMIT_DEFAULT),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items, total, page, limit = await conversation_service.list_conversations(db, user_id, page, limit)
    return ConversationListResponse(
        conversations=[ConversationListItem.model_validate(item) for item in items],
        total=total,
        page=page,
        limit=limit,
        has_next=page * limit < total,
    )


@router.post("", response_model=ConversationCreated, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """마이크를 켜기 전에 부른다 — STT 소켓 주소(/ws/conversations/{id}/stt)에 id 가 필요해서."""
    return await conversation_service.create_conversation(db, user_id, payload)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await conversation_service.get_conversation_detail(db, user_id, conversation_id)


@router.post("/{conversation_id}/end", response_model=ConversationEnded)
async def end_conversation(
    conversation_id: int,
    payload: ConversationEndRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """대화 전체를 한 번에 저장하고 제목/요약을 만든다. 버블이 없으면 FE 는 이 대신 DELETE 를 부른다."""
    return await conversation_service.end_conversation(db, user_id, conversation_id, payload.bubbles)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await conversation_service.delete_conversation(db, user_id, conversation_id)
    return {"ok": True}
