from decimal import Decimal

import pytest

from app import exceptions as exc
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


async def test_transfer_insufficient_funds(session):
    user, _ = await get_or_create_user(session, 12345)
    account1 = await create_account(
        session, user.id, "test1", "cash", "USD", initial_balance=Decimal("100")
    )
    account2 = await create_account(session, user.id, "test2", "cash", "USD")
    with pytest.raises(exc.InsufficientFunds):
        await create_transfer(
            session, user.id, account1.id, account2.id, Decimal("500")
        )
    account1_id = account1.id
    account2_id = account2.id
    session.expire_all()
    account1 = await session.get(Account, account1_id)
    account2 = await session.get(Account, account2_id)
    assert account1.balance == 100
    assert account2.balance == 0


async def test_transfer_different_currency(session):
    user, _ = await get_or_create_user(session, 12345)
    account1 = await create_account(
        session, user.id, "test1", "cash", "USD", initial_balance=Decimal("1000")
    )
    account2 = await create_account(session, user.id, "test2", "cash", "BYN")
    with pytest.raises(exc.DifferentCurrency):
        await create_transfer(
            session, user.id, account1.id, account2.id, Decimal("500")
        )
    account1_id = account1.id
    account2_id = account2.id
    session.expire_all()
    account1 = await session.get(Account, account1_id)
    account2 = await session.get(Account, account2_id)
    assert account1.balance == 1000
    assert account2.balance == 0


async def test_transfer_foreign_account(session):
    user, _ = await get_or_create_user(session, 12345)
    user2, _ = await get_or_create_user(session, 12346)
    account1 = await create_account(
        session, user2.id, "test1", "cash", "USD", initial_balance=Decimal("1000")
    )
    account2 = await create_account(session, user.id, "test2", "cash", "USD")
    with pytest.raises(exc.ForeignAccount):
        await create_transfer(
            session, user2.id, account1.id, account2.id, Decimal("500")
        )
    account1_id = account1.id
    account2_id = account2.id
    session.expire_all()
    account1 = await session.get(Account, account1_id)
    account2 = await session.get(Account, account2_id)
    assert account1.balance == 1000
    assert account2.balance == 0


async def test_transfer_invalid_amount(session):
    user, _ = await get_or_create_user(session, 12345)
    account1 = await create_account(
        session, user.id, "test1", "cash", "USD", initial_balance=Decimal("1000")
    )
    account2 = await create_account(session, user.id, "test2", "cash", "USD")
    with pytest.raises(exc.InvalidAmount):
        await create_transfer(
            session, user.id, account1.id, account2.id, Decimal("-500")
        )
    with pytest.raises(exc.InvalidAmount):
        await create_transfer(session, user.id, account1.id, account2.id, Decimal("0"))
    account1_id = account1.id
    account2_id = account2.id
    session.expire_all()
    account1 = await session.get(Account, account1_id)
    account2 = await session.get(Account, account2_id)
    assert account1.balance == 1000
    assert account2.balance == 0


async def test_transfer_same_account(session):
    user, _ = await get_or_create_user(session, 12345)
    account1 = await create_account(
        session, user.id, "test1", "cash", "USD", initial_balance=Decimal("1000")
    )
    with pytest.raises(exc.SameAccount):
        await create_transfer(
            session, user.id, account1.id, account1.id, Decimal("500")
        )
    account1_id = account1.id
    session.expire_all()
    account1 = await session.get(Account, account1_id)
    assert account1.balance == 1000
