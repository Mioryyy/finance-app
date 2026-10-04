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
