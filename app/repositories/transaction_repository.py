from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories.account_repository import update_balance


async def get_stats(session: AsyncSession, account_id, period: date):
    stmt = (
        select(Category.name, func.sum(Transaction.amount))
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.account_id == account_id,
            Category.type == "expense",
            func.extract("month", Transaction.date) == period.month,
            func.extract("year", Transaction.date) == period.year,
        )
        .group_by(Category.name)
    )
    result = await session.execute(stmt)
    return result.all()

async def get_transactions_for_user(session: AsyncSession, account_id):
    stmt = (select(Transaction).where(Transaction.account_id == account_id))
    result = await session.execute(stmt)
    return result.scalars().all()

async def delete_transaction_by_id(session: AsyncSession, transaction_id: int):
    stmt = (select(Transaction).where(Transaction.id == transaction_id))
    result = await session.execute(stmt)
    transaction = result.scalar_one_or_none()
    if transaction:
        await session.delete(transaction)
        await session.flush()
        return True
    return False


async def create_transaction(
    session: AsyncSession,
    account_id,
    category_id,
    description,
    amount,
    tx_type,
    tr_date=None,
):
    if tr_date is None:
        tr_date = date.today()  # noqa: DTZ011
    new_transaction = Transaction(
        account_id=account_id,
        category_id=category_id,
        description=description,
        amount=amount,
        date=tr_date,
    )
    session.add(new_transaction)
    if tx_type == "expense":
        await update_balance(session, account_id, -amount)
    else:
        await update_balance(session, account_id, amount)

async def get_recent_transactions(session, account_id, offset = 0, limit=10):
    stmt = (select(Transaction, Category.name, Category.type)
            .join(Category, Transaction.category_id == Category.id)
            .where(Transaction.account_id == account_id)
            .offset(offset)
            .limit(limit+1)
            .order_by(Transaction.date.desc(), Transaction.id.desc()))
    result = await session.execute(stmt)
    rows = result.all()
    has_more = len(rows) > limit
    return has_more, rows[:limit]