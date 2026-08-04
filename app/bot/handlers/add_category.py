from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import CategoryStates
from app.database import async_session_maker
from app.models.category import Category
from app.repositories.user_repository import get_or_create_user

router = Router()


@router.message(Command("add_category"))
async def cmd_add_category(message: Message, state: FSMContext):
    await message.answer("Введите название категории")
    await state.set_state(CategoryStates.waiting_for_new_category_name)


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
    async with async_session_maker() as session:
        user_id = await get_or_create_user(
            session=session, telegram_id=message.from_user.id
        )
        new_category = Category(name=new_category_name, owner_id=user_id.id)
        session.add(new_category)
        await session.commit()
    await message.answer("Категория добавлена")
    await state.clear()


@router.callback_query(F.data == "skip", CategoryStates.waiting_for_emoji)
async def process_skip_emoji(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_category_name = data["new_category_name"]
    async with async_session_maker() as session:
        user_id = await get_or_create_user(
            session=session, telegram_id=callback.from_user.id
        )
        new_category = Category(name=new_category_name, owner_id=user_id.id)
        session.add(new_category)
        await session.commit()
    await callback.message.answer("Категория добавлена")
    await callback.answer()
    await state.clear()
