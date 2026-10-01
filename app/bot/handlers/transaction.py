from datetime import date
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import TransactionStates
from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.models.transaction import Transaction
from app.repositories.account_repository import get_account, update_balance
from app.repositories.category_repository import get_categories_for_user, get_category
from app.repositories.user_repository import get_or_create_user

router = Router()


@router.message()
async def add_transaction(message: Message, state: FSMContext):
    if not message.text:
        return
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, message.from_user.id)
        if user.active_account_id is None:
            await message.answer(
                "❌ У тебя ещё нет счёта. Набери /start, чтобы создать его."
            )
            return
    parts = message.text.split()
    if not parts:
        return
    *name_parts, amount = parts
    try:
        amount = Decimal(amount)
    except InvalidOperation:
        await message.answer(
            "❌ Не могу распознать сумму.\n\n"
            "Напиши в формате: <b>описание сумма</b>\n"
            "Например: <i>кофе 50</i>"
        )
        return
    description = " ".join(name_parts)
    await state.update_data(description=description, amount=amount)

    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Расход", callback_data="txtype:expense")
    builder.button(text="💰 Доход", callback_data="txtype:income")
    builder.adjust(2)
    keyboard = builder.as_markup()
    await message.answer("💸 Это трата или пополнение?", reply_markup=keyboard)
    await state.set_state(TransactionStates.waiting_for_type)


@router.callback_query(F.data.startswith("txtype:"), TransactionStates.waiting_for_type)
async def process_transaction_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    tx_type = callback.data.split(":")[1]
    await state.update_data(tx_type=tx_type)
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
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
    await callback.message.answer(text="Выбери категорию", reply_markup=keyboard)
    await state.set_state(TransactionStates.waiting_for_category)
    await callback.answer()


@router.callback_query(F.data.startswith("category:"))
async def handle_category_callback(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    description = data["description"]
    amount = data["amount"]
    today = date.today()  # noqa: DTZ011
    tx_type = data["tx_type"]
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        new_expense = Transaction(
            account_id=user.active_account_id,
            category_id=category_id,
            description=description,
            amount=amount,
            date=today,
        )
        session.add(new_expense)
        category = await get_category(session, category_id)
        account = await get_account(session, user.active_account_id)
        currency_symbol = CURRENCY_SYMBOLS.get(account.currency, account.currency)
        if tx_type == "expense":
            await update_balance(session, user.active_account_id, -amount)
        else:
            await update_balance(session, user.active_account_id, amount)
        await session.commit()

    await callback.message.edit_text(
        f"✅ Транзакция <b>{description}</b> ({amount}{currency_symbol}) записана в категорию <b>{category}</b>"
    )
    await state.clear()
