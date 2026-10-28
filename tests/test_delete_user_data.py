from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.transfer import Transfer
from app.models.user import User
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.transfer_repository import create_transfer
from app.repositories.user_repository import (
    count_user_data,
    delete_user_data,
    get_or_create_user,
    get_user,
    set_active_account,
)

EMPTY = {"accounts": 0, "transactions": 0, "transfers": 0, "categories": 0}
FILLED = {"accounts": 2, "transactions": 2, "transfers": 1, "categories": 1}


async def total(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def fill(session, telegram_id):
    """Пользователь с двумя счетами, операциями, переводом и своей категорией."""
    user, _ = await get_or_create_user(session, telegram_id)
    card = await create_account(
        session, user.id, "Карта", "card", "BYN", Decimal("100")
    )
    cash = await create_account(session, user.id, "Нал", "cash", "BYN", Decimal("50"))
    await set_active_account(session, user, card.id)
    food = await get_or_create_default_category(session, "🍔 Еда", "expense")
    own = Category(name="🐶 Собака", owner_id=user.id, type="expense")
    session.add(own)
    await session.flush()
    await create_transaction(
        session, card.id, food.id, "кофе", Decimal("5"), "expense", date(2026, 10, 1)
    )
    await create_transaction(
        session, cash.id, own.id, "корм", Decimal("7"), "expense", date(2026, 10, 2)
    )
    await create_transfer(session, user.id, card.id, cash.id, Decimal("10"))
    user_id = user.id  # до commit: после него объекты устаревают
    await session.commit()
    return user_id


async def test_count_user_data(session):
    user_id = await fill(session, 111)
    assert await count_user_data(session, user_id) == FILLED


async def test_delete_removes_everything_of_the_user(session):
    user_id = await fill(session, 111)
    await delete_user_data(session, user_id)
    assert await count_user_data(session, user_id) == EMPTY
    assert await get_user(session, 111) is None
    assert await total(session, Account) == 0
    assert await total(session, Transaction) == 0
    assert await total(session, Transfer) == 0


async def test_other_users_data_is_untouched(session):
    mine = await fill(session, 111)
    theirs = await fill(session, 222)
    await delete_user_data(session, mine)
    await session.commit()
    assert await count_user_data(session, theirs) == FILLED
    assert await get_user(session, 222) is not None
    assert await total(session, User) == 1


async def test_shared_categories_survive(session):
    user_id = await fill(session, 111)
    await delete_user_data(session, user_id)
    await session.commit()
    shared = await session.scalar(
        select(func.count()).select_from(Category).where(Category.owner_id.is_(None))
    )
    assert shared == 1  # «🍔 Еда» принадлежит всем, её не удаляют
    assert await total(session, Category) == 1  # а своя «🐶 Собака» удалена


async def test_user_without_accounts_can_be_deleted(session):
    user, _ = await get_or_create_user(session, 333)
    user_id = user.id
    await session.commit()
    await delete_user_data(session, user_id)
    assert await get_user(session, 333) is None


async def test_get_user_does_not_create_anyone(session):
    assert await get_user(session, 424242) is None
    assert await total(session, User) == 0


async def test_user_can_come_back_with_a_clean_slate(session):
    user_id = await fill(session, 111)
    await delete_user_data(session, user_id)
    await session.commit()
    user, is_new = await get_or_create_user(session, 111)
    assert is_new
    assert user.active_account_id is None
    assert await count_user_data(session, user.id) == EMPTY


async def test_repository_only_flushes_so_rollback_restores_everything(session):
    # правило проекта: commit делает хендлер, значит, до него ничего не окончательно
    user_id = await fill(session, 111)
    await delete_user_data(session, user_id)
    assert await count_user_data(session, user_id) == EMPTY
    await session.rollback()
    assert await count_user_data(session, user_id) == FILLED
    assert await get_user(session, 111) is not None
