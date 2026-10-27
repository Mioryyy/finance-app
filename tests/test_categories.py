from app.models.category import Category
from app.repositories.category_repository import (
    base_category_name,
    category_name_exists,
    get_or_create_default_category,
    get_user_category,
)
from app.repositories.user_repository import get_or_create_user


async def test_get_user_category_default_and_own(session):
    user, _ = await get_or_create_user(session, 12345)
    default = await get_or_create_default_category(session, "Еда", "expense")
    own = Category(name="Моя", owner_id=user.id, type="expense")
    session.add(own)
    await session.flush()
    assert await get_user_category(session, default.id, user.id, "expense")
    assert await get_user_category(session, own.id, user.id, "expense")


async def test_get_user_category_foreign(session):
    user, _ = await get_or_create_user(session, 12345)
    other, _ = await get_or_create_user(session, 54321)
    foreign = Category(name="Чужая", owner_id=other.id, type="expense")
    session.add(foreign)
    await session.flush()
    assert await get_user_category(session, foreign.id, user.id, "expense") is None


async def test_get_user_category_wrong_type(session):
    user, _ = await get_or_create_user(session, 12345)
    income = await get_or_create_default_category(session, "Зарплата", "income")
    assert await get_user_category(session, income.id, user.id, "expense") is None


def test_base_category_name():
    assert base_category_name("🍔 Еда") == "еда"
    assert base_category_name("Еда") == "еда"
    assert base_category_name("  🎮🎲 Игры ") == "игры"


async def test_category_name_exists(session):
    user, _ = await get_or_create_user(session, 12345)
    other, _ = await get_or_create_user(session, 54321)
    await get_or_create_default_category(session, "🍔 Еда", "expense")
    session.add(Category(name="Подписки", owner_id=user.id, type="expense"))
    session.add(Category(name="Чужая", owner_id=other.id, type="expense"))
    await session.flush()
    assert await category_name_exists(session, user.id, "еда")
    assert await category_name_exists(session, user.id, "🎉 подписки")
    assert not await category_name_exists(session, user.id, "Чужая")
    assert not await category_name_exists(session, user.id, "Спорт")
