from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import TransactionStates
from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.parsing import parse_amount
from app.repositories.account_repository import get_account
from app.repositories.category_repository import get_category, show_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user

router = Router()


@router.message(StateFilter(None))
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
    *name_parts, raw_amount = parts
    amount = parse_amount(raw_amount)
    if amount is None:
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
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2, 1)
    keyboard = builder.as_markup()
    await message.answer("💸 Это трата или пополнение?", reply_markup=keyboard)
    await state.set_state(TransactionStates.waiting_for_type)


@router.callback_query(F.data.startswith("txtype:"), TransactionStates.waiting_for_type)
async def process_transaction_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    tx_type = callback.data.split(":")[1]
    await state.update_data(tx_type=tx_type)
    builder = InlineKeyboardBuilder()
    builder.button(text="Сегодня", callback_data="date:today")
    builder.button(text="Указать вручную", callback_data="date:manual")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2, 1)
    keyboard = builder.as_markup()
    await callback.message.answer("Укажи дату", reply_markup=keyboard)
    await state.set_state(TransactionStates.waiting_for_date)


@router.callback_query(F.data == "date:today", TransactionStates.waiting_for_date)
async def process_date_today(callback: CallbackQuery, state: FSMContext):
    tr_date = date.today()  # noqa: DTZ011
    await state.update_data(tr_date=tr_date)
    data = await state.get_data()
    tx_type = data["tx_type"]
    await show_category(callback.message.answer, state, tx_type, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "date:manual", TransactionStates.waiting_for_date)
async def process_date_manual(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Напиши дату в формате дд.мм.гггг")
    await state.set_state(TransactionStates.waiting_for_date)
    await callback.answer()


@router.message(TransactionStates.waiting_for_date)
async def parse_date_manual(message: Message, state: FSMContext):
    text = message.text
    try:
        tr_date = datetime.strptime(text, "%d.%m.%Y").date()  # noqa: DTZ007
    except ValueError:
        await message.answer("Напиши дату в формате дд.мм.гггг!")
        return
    await state.update_data(tr_date=tr_date)
    data = await state.get_data()
    tx_type = data["tx_type"]
    await show_category(message.answer, state, tx_type, message.from_user.id)


@router.callback_query(
    F.data.startswith("category:"), TransactionStates.waiting_for_category
)
async def handle_category_callback(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    description = data["description"]
    amount = data["amount"]
    tx_type = data["tx_type"]
    tr_date = data["tr_date"]
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        await create_transaction(
            session,
            user.active_account_id,
            category_id,
            description,
            amount,
            tx_type,
            tr_date,
        )
        category = await get_category(session, category_id)
        account = await get_account(session, user.active_account_id)
        currency_symbol = CURRENCY_SYMBOLS.get(account.currency, account.currency)
        category_name = category.name
        await session.commit()

    await callback.message.edit_text(
        f"✅ Транзакция <b>{description}</b> ({amount}{currency_symbol}) записана в категорию <b>{category_name}</b>"
    )
    await state.clear()


@router.callback_query(F.data.startswith("category:"))
async def handle_category_oldcallback(callback: CallbackQuery):
    await callback.answer("Кнопка устарела, отправь трату заново", show_alert=True)
    await callback.message.delete()
