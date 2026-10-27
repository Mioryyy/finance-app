from datetime import date
from decimal import Decimal

from app.models.category import Category
from app.repositories.account_repository import create_account
from app.repositories.category_repository import (
    get_or_create_default_category,
    guess_category_from_history,
)
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user


async def add(
    session, account, category, description, amount="10", tx_type=None, day=1
):
    # карта: ей можно уходить в минус, поэтому баланс в тестах не мешает
    await create_transaction(
        session,
        account.id,
        category.id,
        description,
        Decimal(amount),
        tx_type or category.type,
        date(2026, 10, day),
    )


async def setup(session, telegram_id=12345):
    user, _ = await get_or_create_user(session, telegram_id)
    account = await create_account(session, user.id, "карта", "card", "BYN")
    return user, account


async def test_finds_category_by_description(session):
    user, account = await setup(session)
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    await add(session, account, food, "кофе")
    guess = await guess_category_from_history(session, user.id, "кофе", "expense")
    assert guess.id == food.id


async def test_ignores_case_and_spaces_in_cyrillic(session):
    user, account = await setup(session)
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    await add(session, account, food, "  Кофе ")
    guess = await guess_category_from_history(session, user.id, "кОфЕ", "expense")
    assert guess.id == food.id


async def test_unknown_description_returns_none(session):
    user, account = await setup(session)
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    await add(session, account, food, "кофе")
    assert (
        await guess_category_from_history(session, user.id, "такси", "expense") is None
    )


async def test_picks_most_frequent_category(session):
    user, account = await setup(session)
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    fun = await get_or_create_default_category(session, "🎉 Развлечения", "expense")
    await add(session, account, fun, "кино", day=5)
    await add(session, account, food, "кино", day=1)
    await add(session, account, food, "кино", day=2)
    guess = await guess_category_from_history(session, user.id, "кино", "expense")
    assert guess.id == food.id


async def test_tie_goes_to_most_recent(session):
    user, account = await setup(session)
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    fun = await get_or_create_default_category(session, "🎉 Развлечения", "expense")
    await add(session, account, food, "кино", day=1)
    await add(session, account, fun, "кино", day=9)
    guess = await guess_category_from_history(session, user.id, "кино", "expense")
    assert guess.id == fun.id


async def test_uses_all_accounts_of_the_user(session):
    user, card = await setup(session)
    cash = await create_account(session, user.id, "нал", "cash", "BYN", Decimal("100"))
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    await add(session, cash, food, "кофе")
    guess = await guess_category_from_history(session, user.id, "кофе", "expense")
    assert guess.id == food.id


async def test_other_users_history_is_not_used(session):
    user, _ = await setup(session)
    other, other_account = await setup(session, telegram_id=54321)
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    await add(session, other_account, food, "кофе")
    assert (
        await guess_category_from_history(session, user.id, "кофе", "expense") is None
    )


async def test_empty_description_returns_none(session):
    user, account = await setup(session)
    income = await get_or_create_default_category(session, "💼 Зарплата", "income")
    await add(session, account, income, None)
    assert await guess_category_from_history(session, user.id, None, "income") is None
    assert await guess_category_from_history(session, user.id, "   ", "income") is None


async def test_type_must_match(session):
    user, account = await setup(session)
    income = await get_or_create_default_category(session, "💼 Зарплата", "income")
    await add(session, account, income, "аванс")
    assert (
        await guess_category_from_history(session, user.id, "аванс", "expense") is None
    )
    guess = await guess_category_from_history(session, user.id, "аванс", "income")
    assert guess.id == income.id


async def test_own_category_is_returned(session):
    user, account = await setup(session)
    own = Category(name="🐶 Собака", owner_id=user.id, type="expense")
    session.add(own)
    await session.flush()
    await add(session, account, own, "корм")
    guess = await guess_category_from_history(session, user.id, "корм", "expense")
    assert guess.id == own.id
