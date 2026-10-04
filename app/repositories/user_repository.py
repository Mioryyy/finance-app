from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_or_create_user(session: AsyncSession, telegram_id: int):
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        return user, False
    new_user = User(telegram_id=telegram_id)
    session.add(new_user)
    await session.flush()
    return new_user, True


async def set_active_account(session: AsyncSession, user, account_id: int):
    user.active_account_id = account_id
    await session.flush()
