from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.notification import (
    NotificationDeleteRequest,
    NotificationDeleteResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.services import notification_service

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    cursor: str | None = Query(None, description="이전 응답의 next_cursor. 없으면 최신부터"),
    # ge/le 를 걸지 않는 건 의도 — 범위를 벗어나면 400 대신 서비스에서 잘라낸다.
    # 무한 스크롤 도중 400 이 나면 화면이 이유 없이 멈춘다.
    limit: int = Query(notification_service.LIST_LIMIT_DEFAULT),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.list_notifications(db, user_id, cursor, limit)


@router.post("/delete", response_model=NotificationDeleteResponse)
async def delete_notifications(
    payload: NotificationDeleteRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """선택 삭제. DELETE 대신 POST 인 이유: [전체 선택]로 ids 가 수백 개가 될 수 있어
    쿼리스트링은 URL 길이 제한에 걸리고, DELETE 의 요청 바디는 RFC 9110 상 의미가 정의돼
    있지 않아 일부 프록시가 조용히 버린다(→ 0건 삭제됐는데 응답은 성공)."""
    deleted_count = await notification_service.delete_notifications(db, user_id, payload.ids)
    return NotificationDeleteResponse(deleted_count=deleted_count)


@router.post("/delete-all", response_model=NotificationDeleteResponse)
async def delete_all_notifications(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    deleted_count = await notification_service.delete_all_notifications(db, user_id)
    return NotificationDeleteResponse(deleted_count=deleted_count)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(notification_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await notification_service.mark_read(db, user_id, notification_id)


@router.delete("/{notification_id}")
async def delete_notification(notification_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await notification_service.delete_notification(db, user_id, notification_id)
    return {"ok": True}
