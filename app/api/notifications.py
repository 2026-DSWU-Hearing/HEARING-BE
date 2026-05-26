from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_current_user_id, get_db
from app.schemas.notification import NotificationResponse
from app.services import notification_service

router = APIRouter()


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.list_notifications(db, user_id, page, size)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(notification_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await notification_service.mark_read(db, user_id, notification_id)


@router.delete("/{notification_id}")
async def delete_notification(notification_id: int, user_id: int = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await notification_service.delete_notification(db, user_id, notification_id)
    return {"ok": True}
