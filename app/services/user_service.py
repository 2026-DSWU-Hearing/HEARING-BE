from sqlalchemy.ext.asyncio import AsyncSession

from app.db.functions import get_or_404
from app.models.user import User
from app.schemas.user import AgreementUpdate, DoNotDisturbUpdate, FcmTokenUpdate, HapticUpdate, PushEnabledUpdate, UserUpdate


async def get_me(db: AsyncSession, user_id: int) -> User:
    return await get_or_404(db, User, user_id)


async def update_profile(db: AsyncSession, user_id: int, payload: UserUpdate) -> User:
    user = await get_or_404(db, User, user_id)
    if payload.nickname is not None:
        user.nickname = payload.nickname
    if payload.disability_type is not None:
        user.disability_type = payload.disability_type
    await db.commit()
    await db.refresh(user)
    return user


async def update_haptic(db: AsyncSession, user_id: int, payload: HapticUpdate) -> User:
    user = await get_or_404(db, User, user_id)
    user.haptic_strength = payload.haptic_strength
    await db.commit()
    await db.refresh(user)
    return user


async def update_do_not_disturb(db: AsyncSession, user_id: int, payload: DoNotDisturbUpdate) -> User:
    user = await get_or_404(db, User, user_id)
    user.do_not_disturb = payload.do_not_disturb
    await db.commit()
    await db.refresh(user)
    return user


async def update_push_enabled(db: AsyncSession, user_id: int, payload: PushEnabledUpdate) -> User:
    user = await get_or_404(db, User, user_id)
    user.push_enabled = payload.push_enabled
    await db.commit()
    await db.refresh(user)
    return user


async def update_fcm_token(db: AsyncSession, user_id: int, payload: FcmTokenUpdate) -> User:
    user = await get_or_404(db, User, user_id)
    user.fcm_token = payload.fcm_token
    await db.commit()
    await db.refresh(user)
    return user


async def update_agreement(db: AsyncSession, user_id: int, payload: AgreementUpdate) -> User:
    user = await get_or_404(db, User, user_id)
    user.terms_agreed = payload.terms_agreed
    await db.commit()
    await db.refresh(user)
    return user
