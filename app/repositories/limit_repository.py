import calendar
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.limit import CategoryLimit
from app.models.transaction import Transaction


async def set_limit(session: AsyncSession, user_id, category_id, currency, amount):
    # один лимит на пару «категория + валюта»: повторный вызов меняет сумму
    existing = await get_limit(session, user_id, category_id, currency)
    if existing:
        existing.amount = amount
        await session.flush()
        return existing
    limit = CategoryLimit(
        user_id=user_id, category_id=category_id, currency=currency, amount=amount
    )
    session.add(limit)
    await session.flush()
    return limit


async def get_limit(session: AsyncSession, user_id, category_id, currency):
    stmt = select(CategoryLimit).where(
        CategoryLimit.user_id == user_id,
        CategoryLimit.category_id == category_id,
        CategoryLimit.currency == currency,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_limits(session: AsyncSession, user_id):
    # (лимит, название категории) всех лимитов пользователя
    stmt = (
        select(CategoryLimit, Category.name)
        .join(Category, CategoryLimit.category_id == Category.id)
        .where(CategoryLimit.user_id == user_id)
        .order_by(CategoryLimit.id)
    )
    return (await session.execute(stmt)).all()


async def delete_limit(session: AsyncSession, limit_id, user_id) -> bool:
    # id из кнопки не доверяем: удаляем только свой лимит
    result = await session.execute(
        delete(CategoryLimit).where(
            CategoryLimit.id == limit_id, CategoryLimit.user_id == user_id
        )
    )
    await session.flush()
    return result.rowcount > 0


async def month_spent(session: AsyncSession, user_id, category_id, currency, day: date):
    # сколько пользователь потратил в категории за месяц, к которому относится
    # day, по всем его счетам этой валюты
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    stmt = (
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Account, Transaction.account_id == Account.id)
        .where(
            Account.owner_id == user_id,
            Account.currency == currency,
            Transaction.category_id == category_id,
            Transaction.date >= first,
            Transaction.date <= last,
        )
    )
    return await session.scalar(stmt)
