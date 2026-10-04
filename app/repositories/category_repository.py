from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.states import TransactionStates
from app.database import async_session_maker
from app.models.category import Category
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


async def show_category(answer_func, state: FSMContext, tx_type: str, user_id: int):
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
    builder.button(text="➕ Добавить категорию", callback_data="category_add")
    adjust.append(1)
    builder.adjust(*adjust)
    keyboard = builder.as_markup()
    await answer_func(text="Выбери категорию", reply_markup=keyboard)
    await state.set_state(TransactionStates.waiting_for_category)
