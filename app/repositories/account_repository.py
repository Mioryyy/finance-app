from decimal import Decimal

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import exceptions as exc
from app.constants import OVERDRAFT_ACCOUNT_TYPES
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.transfer import Transfer


async def create_account(
    session: AsyncSession,
    owner_id,
    name,
    account_type,
    currency,
    initial_balance=Decimal("0"),
):
    new_account = Account(
        name=name,
        balance=initial_balance,
        type=account_type,
        currency=currency,
        owner_id=owner_id,
    )
    session.add(new_account)
    await session.flush()
    return new_account


async def update_balance(session: AsyncSession, account_id, delta):
    # проверка остатка и изменение в одном UPDATE: между ними не вклинится
    # другой запрос, который успеет потратить те же деньги
    stmt = (
        update(Account)
        .where(
            Account.id == account_id,
            or_(
                Account.type.in_(OVERDRAFT_ACCOUNT_TYPES),
                Account.balance + delta >= 0,
            ),
        )
        .values(balance=Account.balance + delta)
        .returning(Account.balance)
    )
    result = await session.execute(stmt)
    new_balance = result.scalar_one_or_none()
    if new_balance is None:
        raise exc.InsufficientFunds
    return new_balance


async def get_accounts_for_user(session: AsyncSession, user_id):
    stmt = select(Account).where(Account.owner_id == user_id).order_by(Account.id)
    result = await session.execute(stmt)
    accounts = result.scalars().all()
    return accounts


async def get_account(session: AsyncSession, account_id):
    stmt = select(Account).where(Account.id == account_id)
    result = await session.execute(stmt)
    account = result.scalar_one()
    return account


async def get_user_account(session: AsyncSession, account_id, user_id):
    stmt = select(Account).where(Account.id == account_id, Account.owner_id == user_id)
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    return account


async def rename_account(session: AsyncSession, account, name: str):
    account.name = name
    await session.flush()


async def set_account_type(session: AsyncSession, account, account_type: str):
    # наличные и крипта не уходят в минус (то же правило — CHECK в базе)
    if account_type not in OVERDRAFT_ACCOUNT_TYPES and account.balance < 0:
        raise exc.InsufficientFunds
    account.type = account_type
    await session.flush()


async def account_has_operations(session: AsyncSession, account_id) -> bool:
    has_transactions = exists().where(Transaction.account_id == account_id)
    has_transfers = exists().where(
        or_(
            Transfer.from_account_id == account_id, Transfer.to_account_id == account_id
        )
    )
    return await session.scalar(select(has_transactions | has_transfers))


async def set_starting_balance(session: AsyncSession, account, amount):
    # только у пустого счёта: иначе баланс перестанет сходиться с историей
    if await account_has_operations(session, account.id):
        raise exc.AccountHasOperations
    account.balance = amount
    await session.flush()
