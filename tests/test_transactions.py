from app.models.account import Account
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import (
    create_transaction,
    delete_transaction_by_id,
)
from app.repositories.user_repository import get_or_create_user


async def test_delete_expense_restores_balance(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "cash", "USD")
    category = await get_or_create_default_category(session, "test", "expense")
    transaction = await create_transaction(
        session, account.id, category.id, "test_transaction", 100, category.type
    )
    account_id = account.id
    transaction_id = transaction.id
    session.expire_all()
    account = await session.get(Account, account_id)
    assert account.balance == -100
    deleted = await delete_transaction_by_id(session, transaction_id, account_id)
    session.expire_all()
    account = await session.get(Account, account_id)
    assert deleted
    assert account.balance == 0


async def test_delete_income_reduces_balance(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "cash", "USD")
    category = await get_or_create_default_category(session, "test", "income")
    transaction = await create_transaction(
        session, account.id, category.id, "test_transaction", 100, category.type
    )
    account_id = account.id
    transaction_id = transaction.id
    session.expire_all()
    account = await session.get(Account, account_id)
    assert account.balance == 100
    deleted = await delete_transaction_by_id(session, transaction_id, account_id)
    session.expire_all()
    account = await session.get(Account, account_id)
    assert deleted
    assert account.balance == 0


async def test_delete_foreign_transaction_returns_false(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "cash", "USD")
    account_id = account.id
    category = await get_or_create_default_category(session, "test", "expense")
    transaction = await create_transaction(
        session, account.id, category.id, "test_transaction", 100, category.type
    )
    transaction_id = transaction.id
    user1, _ = await get_or_create_user(session, 12346)
    account1 = await create_account(session, user1.id, "test1", "cash", "USD")
    account1_id = account1.id
    session.expire_all()
    deleted = await delete_transaction_by_id(session, transaction_id, account1_id)
    assert not deleted
    account = await session.get(Account, account_id)
    assert account.balance == -100


async def test_delete_missing_transaction_returns_false(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "cash", "USD")
    category = await get_or_create_default_category(session, "test", "income")
    transaction = await create_transaction(
        session, account.id, category.id, "test_transaction", 100, category.type
    )
    account_id = account.id
    transaction_id = transaction.id + 99999
    session.expire_all()
    deleted = await delete_transaction_by_id(session, transaction_id, account_id)
    assert not deleted
