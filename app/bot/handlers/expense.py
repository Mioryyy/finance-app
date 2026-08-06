from datetime import date
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import ExpenseStates
from app.database import async_session_maker
from app.models.expense import Expense
from app.repositories.category_repository import get_categories_for_user
from app.repositories.user_repository import get_or_create_user

router = Router()


@router.message()
async def add_expense(message: Message, state: FSMContext):
    if not message.text:
        return
    parts = message.text.split()
    if not parts:
        return
    *name_parts, amount = parts
    try:
        amount = Decimal(amount)
    except InvalidOperation:
        await message.answer("введите число")
        return
    description = " ".join(name_parts)
    await state.update_data(description=description, amount=amount)
    await state.set_state(ExpenseStates.waiting_for_category)

    async with async_session_maker() as session:
        user = await get_or_create_user(session, message.from_user.id)
        categories = await get_categories_for_user(session, user.id)
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
    await message.answer(text="Выбери категорию", reply_markup=keyboard)


@router.callback_query(F.data.startswith("category:"))
async def handle_category_callback(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    description = data["description"]
    amount = data["amount"]
    today = date.today()  # noqa: DTZ011
    async with async_session_maker() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        new_expense = Expense(
            user_id=user.id,
            category_id=category_id,
            description=description,
            amount=amount,
            date=today,
        )
        session.add(new_expense)
        await session.commit()
    await callback.message.edit_text("Трата записана")
    await state.clear()
