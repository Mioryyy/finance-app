import asyncio
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import CategoryStates
from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories.account_repository import get_account, update_balance
from app.repositories.user_repository import get_or_create_user

router = Router()


async def finalize_category_creation(telegram_id, name, data):
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(
            session=session, telegram_id=telegram_id
        )
        tx_type = data["tx_type"]
        new_category = Category(name=name, owner_id=user.id, type=tx_type)
        session.add(new_category)
        await session.flush()
        currency_symbol = None
        if data.get("description"):
            account_id = user.active_account_id
            account = await get_account(session, account_id)
            currency_symbol = CURRENCY_SYMBOLS.get(account.currency, account.currency)
            category_id = new_category.id
            description = data["description"]
            amount = data["amount"]
            today = date.today()  # noqa: DTZ011
            new_transaction = Transaction(
                account_id=account_id,
                category_id=category_id,
                description=description,
                amount=amount,
                date=today,
            )
            session.add(new_transaction)
            if tx_type == "expense":
                await update_balance(session, account_id, -amount)
            else:
                await update_balance(session, account_id, amount)
        await session.commit()
    return (
        bool(data.get("description")),
        data.get("description"),
        data.get("amount"),
        currency_symbol,
    )


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
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("🏷 Как назовём новую категорию?")
    await state.set_state(CategoryStates.waiting_for_new_category_name)
    await callback.answer()


@router.message(CategoryStates.waiting_for_new_category_name)
async def process_category_name(message: Message, state: FSMContext):
    new_category_name = message.text
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
    data = await state.get_data()
    new_category_name = f"{message.text} {data['new_category_name']}"
    expense_created, description, amount, currency_symbol = (
        await finalize_category_creation(message.from_user.id, new_category_name, data)
    )
    if expense_created:
        await message.answer(f"✅ Категория <b>{new_category_name}</b> добавлена")
        await asyncio.sleep(1)
        await message.answer(
            f"✅ Транзакция <b>{description}</b> ({amount}{currency_symbol}) записана в категорию <b>{new_category_name}</b>"
        )
    else:
        await message.answer(f"✅ Категория <b>{new_category_name}</b> добавлена")
    await state.clear()


@router.callback_query(F.data == "skip", CategoryStates.waiting_for_emoji)
async def process_skip_emoji(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_category_name = data["new_category_name"]
    expense_created, description, amount, currency_symbol = (
        await finalize_category_creation(callback.from_user.id, new_category_name, data)
    )
    if expense_created:
        await callback.message.answer(
            f"✅ Категория <b>{new_category_name}</b> добавлена"
        )
        await asyncio.sleep(1)
        await callback.message.answer(
            f"✅ Транзакция <b>{description}</b> ({amount}{currency_symbol}) записана в категорию <b>{new_category_name}</b>"
        )
    else:
        await callback.message.answer(
            f"✅ Категория <b>{new_category_name}</b> добавлена"
        )
    await callback.answer()
    await state.clear()
