import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.entry import show_confirmation
from app.bot.states import CategoryStates
from app.database import async_session_maker
from app.models.category import Category
from app.parsing import looks_like_emoji
from app.repositories.category_repository import category_name_exists
from app.repositories.user_repository import get_or_create_user

router = Router()


async def create_category(telegram_id, name, data):
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(
            session=session, telegram_id=telegram_id
        )
        new_category = Category(name=name, owner_id=user.id, type=data["tx_type"])
        session.add(new_category)
        await session.flush()
        category_id = new_category.id
        await session.commit()
    return category_id


async def finish_category_creation(send_func, state, telegram_id, name, data):
    category_id = await create_category(telegram_id, name, data)
    await send_func(f"✅ Категория <b>{html.escape(name)}</b> добавлена")
    if data.get("amount") is None:
        # категорию создавали отдельной командой, трату записывать не нужно
        await state.clear()
        return
    # категорию создавали прямо из траты: возвращаемся в окно подтверждения с ней
    await state.update_data(
        category_id=category_id, category_name=name, guess_source=None
    )
    await show_confirmation(send_func, state)


async def ask_for_emoji(send_func, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить ", callback_data="skip")
    keyboard = builder.as_markup()
    await send_func(
        text="Хочешь добавить эмодзи для категории? Просто отправь его следующим сообщением, или нажми «Пропустить»",
        reply_markup=keyboard,
    )
    await state.set_state(CategoryStates.waiting_for_emoji)


@router.message(Command("add_category"))
async def cmd_add_category(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏷 Как назовём новую категорию?")
    await state.set_state(CategoryStates.waiting_for_new_category_name)


@router.callback_query(F.data == "category_add")
async def callback_add_category(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await callback.message.delete()
    await callback.message.answer("🏷 Как назовём новую категорию?")
    await state.set_state(CategoryStates.waiting_for_new_category_name)
    await callback.answer()


@router.message(CategoryStates.waiting_for_new_category_name)
async def process_category_name(message: Message, state: FSMContext):
    new_category_name = message.text
    if not new_category_name:
        await message.answer("Отправь название категории текстом")
        return
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        exists = await category_name_exists(session, user.id, new_category_name)
    if exists:
        await message.answer(
            "Такая категория уже есть. Напиши другое название или нажми /cancel"
        )
        return
    await state.update_data(new_category_name=new_category_name)
    data = await state.get_data()

    if data.get("tx_type"):
        await ask_for_emoji(message.answer, state)
        return
    else:
        builder = InlineKeyboardBuilder()
        builder.button(text="💸 Расход", callback_data="txtype:expense")
        builder.button(text="💰 Доход", callback_data="txtype:income")
        builder.adjust(2)
        keyboard = builder.as_markup()
        await message.answer(
            "💸 Категория для трат или пополнений?", reply_markup=keyboard
        )
        await state.set_state(CategoryStates.waiting_for_type)


@router.callback_query(F.data.startswith("txtype:"), CategoryStates.waiting_for_type)
async def process_category_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    tx_type = callback.data.split(":")[1]
    await state.update_data(tx_type=tx_type)
    await ask_for_emoji(callback.message.answer, state)
    await callback.answer()


@router.message(CategoryStates.waiting_for_emoji)
async def process_category_emoji(message: Message, state: FSMContext):
    if not looks_like_emoji(message.text):
        await message.answer("Отправь один эмодзи или нажми «Пропустить»")
        return
    data = await state.get_data()
    new_category_name = f"{message.text} {data['new_category_name']}"
    await finish_category_creation(
        message.answer, state, message.from_user.id, new_category_name, data
    )


@router.callback_query(F.data == "skip", CategoryStates.waiting_for_emoji)
async def process_skip_emoji(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await finish_category_creation(
        callback.message.answer,
        state,
        callback.from_user.id,
        data["new_category_name"],
        data,
    )
    await callback.answer()
