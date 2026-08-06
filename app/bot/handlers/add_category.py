import asyncio
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import CategoryStates
from app.database import async_session_maker
from app.models.category import Category
from app.models.expense import Expense
from app.repositories.user_repository import get_or_create_user

router = Router()


async def finalize_category_creation(telegram_id, name, data):
    async with async_session_maker() as session:
        user_id = await get_or_create_user(session=session, telegram_id=telegram_id)
        new_category = Category(name=name, owner_id=user_id.id)
        session.add(new_category)
        await session.flush()

        if data.get("description"):
            new_expense = Expense(
                user_id=new_category.owner_id,
                category_id=new_category.id,
                description=data["description"],
                amount=data["amount"],
                date=date.today(),  # noqa: DTZ011
            )
            session.add(new_expense)
        await session.commit()
    return bool(data.get("description"))


@router.message(Command("add_category"))
async def cmd_add_category(message: Message, state: FSMContext):
    await message.answer("Введите название категории")
    await state.set_state(CategoryStates.waiting_for_new_category_name)


@router.callback_query(F.data == "category_add")
async def callback_add_category(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Создаём новую категорию...")
    await callback.message.answer("Введите название категории")
    await state.set_state(CategoryStates.waiting_for_new_category_name)
    await callback.answer()


@router.message(CategoryStates.waiting_for_new_category_name)
async def process_category_name(message: Message, state: FSMContext):
    new_category_name = message.text
    await state.update_data(new_category_name=new_category_name)
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить ", callback_data="skip")
    keyboard = builder.as_markup()
    await message.answer(
        text="Добавбте эмоджи для вашей категории", reply_markup=keyboard
    )
    await state.set_state(CategoryStates.waiting_for_emoji)


@router.message(CategoryStates.waiting_for_emoji)
async def process_category_emoji(message: Message, state: FSMContext):
    data = await state.get_data()
    new_category_name = f"{message.text} {data['new_category_name']}"
    expense_created = await finalize_category_creation(
        message.from_user.id, new_category_name, data
    )
    if expense_created:
        await message.answer("Категория добавлена")
        await asyncio.sleep(1)
        await message.answer("Трата записана")
    else:
        await message.answer("Категория добавлена")
    await state.clear()


@router.callback_query(F.data == "skip", CategoryStates.waiting_for_emoji)
async def process_skip_emoji(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_category_name = data["new_category_name"]
    expense_created = await finalize_category_creation(
        callback.from_user.id, new_category_name, data
    )
    if expense_created:
        await callback.message.answer("Категория добавлена")
        await asyncio.sleep(1)
        await callback.message.answer("Трата записана")
    else:
        await callback.message.answer("Категория добавлена")
    await callback.answer()
    await state.clear()
