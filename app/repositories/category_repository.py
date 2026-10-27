from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.states import TransactionStates
from app.database import async_session_maker
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories.user_repository import get_or_create_user


async def get_categories_for_user(session: AsyncSession, user_id: int, category_type):
    order_key = Category.name.endswith("Другое")
    stmt = (
        select(Category)
        .where(
            or_(Category.owner_id.is_(None), Category.owner_id == user_id),
            Category.type == category_type,
        )
        .order_by(order_key, Category.id)
    )
    result = await session.execute(stmt)
    categories = result.scalars().all()
    return categories


def base_category_name(name: str) -> str:
    # «🍔 Еда» и «еда» считаются одной категорией: убираем эмодзи в начале и регистр
    index = 0
    while index < len(name) and not name[index].isalnum():
        index += 1
    return name[index:].strip().lower()


async def category_name_exists(session: AsyncSession, user_id: int, name: str):
    stmt = select(Category.name).where(
        or_(Category.owner_id.is_(None), Category.owner_id == user_id)
    )
    result = await session.execute(stmt)
    target = base_category_name(name)
    return any(base_category_name(existing) == target for existing in result.scalars())


async def guess_category_from_history(
    session: AsyncSession, user_id: int, description: str | None, category_type: str
):
    # в какую категорию пользователь чаще всего записывал такое описание:
    # «Кофе», «кофе » и «КОФЕ» считаются одним и тем же
    normalized = (description or "").strip().lower()
    if not normalized:
        return None
    stmt = (
        select(Category)
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Account, Account.id == Transaction.account_id)
        .where(
            # все счета пользователя, а не только активный; чужие операции не берём
            Account.owner_id == user_id,
            func.lower(func.trim(Transaction.description)) == normalized,
            Category.type == category_type,
            # категория должна быть доступна пользователю: общая или своя
            or_(Category.owner_id.is_(None), Category.owner_id == user_id),
        )
        .group_by(Category.id)
        # чаще всего; при равенстве — та, что использовалась позже;
        # id в конце делает выбор детерминированным
        .order_by(
            func.count(Transaction.id).desc(),
            func.max(Transaction.date).desc(),
            Category.id,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_default_category(
    session: AsyncSession, name: str, category_type: str
):
    stmt = select(Category).where(
        Category.name == name,
        Category.owner_id.is_(None),
        Category.type == category_type,
    )
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    if category:
        return category
    new_category = Category(name=name, type=category_type)
    session.add(new_category)
    await session.flush()
    return new_category


async def get_category(session: AsyncSession, category_id: int):
    stmt = select(Category).where(Category.id == category_id)
    result = await session.execute(stmt)
    category = result.scalar_one()
    return category


async def get_user_category(
    session: AsyncSession, category_id: int, user_id: int, category_type: str
):
    stmt = select(Category).where(
        Category.id == category_id,
        or_(Category.owner_id.is_(None), Category.owner_id == user_id),
        Category.type == category_type,
    )
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    return category


async def show_category(
    answer_func,
    state: FSMContext,
    tx_type: str,
    user_id: int,
    text: str = "Выбери категорию",
):
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, user_id)
        categories = await get_categories_for_user(session, user.id, tx_type)
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(text=category.name, callback_data=f"category:{category.id}")
    n = len(categories)
    adjust = [2] * (n // 2)
    if n % 2 == 1:
        adjust.append(1)
    builder.button(text="📅 Другая дата", callback_data="date:pick")
    builder.button(text="➕ Добавить категорию", callback_data="category_add")
    adjust.append(2)
    builder.button(text="❌ Отмена", callback_data="cancel")
    adjust.append(1)
    builder.adjust(*adjust)
    keyboard = builder.as_markup()
    await answer_func(text=text, reply_markup=keyboard)
    await state.set_state(TransactionStates.waiting_for_category)
