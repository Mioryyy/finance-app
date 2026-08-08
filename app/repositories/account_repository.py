from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account


async def create_account(session: AsyncSession, owner_id, name, type, currency):
    new_account = Account(
        name=name, balance=0, type=type, currency=currency, owner_id=owner_id
    )
    session.add(new_account)
    await session.flush()
    account_id = new_account.id
    await session.commit()
    return account_id


async def update_balance(session: AsyncSession, account_id, delta):
    stmt = select(Account).where(Account.id == account_id)
    result = await session.execute(stmt)
    account = result.scalar_one()
    account.balance += delta
    await session.commit()


async def get_accounts_for_user(session: AsyncSession, user_id):
    stmt = select(Account).where(Account.owner_id == user_id)
    result = await session.execute(stmt)
    accounts = result.scalars().all()
    return accounts
