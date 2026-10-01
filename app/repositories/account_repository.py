from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account


async def create_account(session: AsyncSession, owner_id, name, account_type, currency):
    new_account = Account(
        name=name, balance=0, type=account_type, currency=currency, owner_id=owner_id
    )
    session.add(new_account)
    await session.flush()
    account_id = new_account.id
    await session.commit()
    return account_id


async def update_balance(session: AsyncSession, account_id, delta):
    stmt = (
        update(Account)
        .where(Account.id == account_id)
        .values(balance=Account.balance + delta)
    )
    await session.execute(stmt)


async def get_accounts_for_user(session: AsyncSession, user_id):
    stmt = select(Account).where(Account.owner_id == user_id)
    result = await session.execute(stmt)
    accounts = result.scalars().all()
    return accounts


async def get_account(session: AsyncSession, account_id: int):
    stmt = select(Account).where(Account.id == account_id)
    result = await session.execute(stmt)
    account = result.scalar_one()
    return account
