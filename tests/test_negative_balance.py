from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import exceptions as exc
from app.models.account import Account
from app.models.transaction import Transaction
from app.repositories.account_repository import create_account, update_balance
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import (
    create_transaction,
    delete_transaction_by_id,
)
from app.repositories.transfer_repository import create_transfer
from app.repositories.user_repository import get_or_create_user


async def balance_of(session, account_id):
    session.expire_all()
    account = await session.get(Account, account_id)
    return account.balance


@pytest.mark.parametrize("account_type", ["cash", "crypto"])
async def test_cash_and_crypto_cannot_go_negative(session, account_type):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(
        session, user.id, "test", account_type, "USD", initial_balance=Decimal("50")
    )
    account_id = account.id
    with pytest.raises(exc.InsufficientFunds):
        await update_balance(session, account_id, Decimal("-50.01"))
    assert await balance_of(session, account_id) == 50
    assert await update_balance(session, account_id, Decimal("-50")) == 0


async def test_card_can_go_negative(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "card", "USD")
    account_id = account.id
    assert await update_balance(session, account_id, Decimal("-30")) == -30
    assert await balance_of(session, account_id) == -30


async def test_expense_over_balance_is_not_saved(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(
        session, user.id, "test", "cash", "USD", initial_balance=Decimal("10")
    )
    account_id = account.id
    category = await get_or_create_default_category(session, "Еда", "expense")
    with pytest.raises(exc.InsufficientFunds):
        await create_transaction(
            session, account_id, category.id, "кофе", Decimal("11"), "expense"
        )
    assert await balance_of(session, account_id) == 10
    count = await session.scalar(select(func.count()).select_from(Transaction))
    assert count == 0


async def test_cannot_delete_spent_income(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "cash", "USD")
    account_id = account.id
    income = await get_or_create_default_category(session, "Зарплата", "income")
    expense = await get_or_create_default_category(session, "Еда", "expense")
    salary = await create_transaction(
        session, account_id, income.id, "зп", Decimal("500"), "income"
    )
    salary_id = salary.id
    await create_transaction(
        session, account_id, expense.id, "аренда", Decimal("450"), "expense"
    )
    with pytest.raises(exc.InsufficientFunds):
        await delete_transaction_by_id(session, salary_id, account_id)
    assert await balance_of(session, account_id) == 50
    assert await session.get(Transaction, salary_id) is not None


async def test_card_transfer_can_overdraft(session):
    user, _ = await get_or_create_user(session, 12345)
    card = await create_account(session, user.id, "card", "card", "USD")
    cash = await create_account(session, user.id, "cash", "cash", "USD")
    card_id, cash_id = card.id, cash.id
    await create_transfer(session, user.id, card_id, cash_id, Decimal("20"))
    assert await balance_of(session, card_id) == -20
    assert await balance_of(session, cash_id) == 20


async def test_database_check_blocks_negative_cash(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "cash", "USD")
    account_id = account.id
    # обходим update_balance: даже так база не даст сохранить минус
    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE accounts SET balance = -1 WHERE id = :id"), {"id": account_id}
        )
    await session.rollback()
