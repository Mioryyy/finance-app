from decimal import Decimal

from app.models.account import Account
from app.models.transfer import Transfer
from app.repositories.account_repository import create_account
from app.repositories.transfer_repository import create_transfer
from app.repositories.user_repository import get_or_create_user


async def test_create_transfer(session):
    user, _ = await get_or_create_user(session, 12345)
    account1 = await create_account(
        session, user.id, "test1", "cash", "USD", initial_balance=Decimal("1000")
    )
    account2 = await create_account(session, user.id, "test2", "cash", "USD")
    transfer = await create_transfer(
        session, user.id, account1.id, account2.id, Decimal(700)
    )
    account1_id = account1.id
    account2_id = account2.id
    transfer_id = transfer.id
    session.expire_all()
    account1 = await session.get(Account, account1_id)
    account2 = await session.get(Account, account2_id)
    transfer = await session.get(Transfer, transfer_id)
    assert account1.balance == 300
    assert account2.balance == 700
    assert transfer.from_account_id == account1_id
    assert transfer.to_account_id == account2_id
    assert transfer.amount == Decimal(700)
