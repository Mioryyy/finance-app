"""Правка уже записанной операции: сумма, описание, дата.

Сюда ведут кнопки карточки операции (review.py). Категорию и удаление
карточка обрабатывает сама, а здесь нужны диалоги: бот спрашивает новое
значение и ждёт сообщение.
"""

from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import exceptions as exc
from app.bot.handlers.review import (
    NOT_FOUND,
    card_keyboard,
    card_text,
    load,
    load_transaction,
)
from app.bot.states import TransactionEditStates
from app.bot.texts import not_enough_money_text
from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.parsing import parse_amount, parse_date
from app.repositories.transaction_repository import (
    set_transaction_amount,
    set_transaction_date,
    set_transaction_description,
)

router = Router()

DESCRIPTION_MAX = 100

EDIT_PROMPTS = {
    "amt": (
        TransactionEditStates.waiting_for_amount,
        "Напиши новую сумму, например: <i>12,5</i>\nПередумал: /cancel",
    ),
    "desc": (
        TransactionEditStates.waiting_for_description,
        "Напиши новое описание, например: <i>кофе с собой</i>\nПередумал: /cancel",
    ),
    "date": (
        TransactionEditStates.waiting_for_date,
        "Напиши дату: <i>вчера</i>, <i>05.11</i> или <i>05.11.2026</i>\n"
        "Передумал: /cancel",
    ),
}


@router.callback_query(F.data.regexp(r"^tx:(amt|desc|date):\d+$"))
async def start_edit(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    async with async_session_maker() as session:
        _user, row = await load(callback, session)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        transaction_id = row[0].id
    new_state, prompt = EDIT_PROMPTS[field]
    await state.clear()
    await state.set_state(new_state)
    await state.update_data(tx_id=transaction_id)
    await callback.message.answer(prompt)
    await callback.answer()


async def save_edit(message: Message, state: FSMContext, apply, title):
    # apply(session, transaction, category, account) меняет операцию и
    # возвращает текст ошибки или None; commit только при успехе
    data = await state.get_data()
    async with async_session_maker() as session:
        _user, row = await load_transaction(
            session, message.from_user.id, data["tx_id"]
        )
        if row is None:
            await state.clear()
            await message.answer(NOT_FOUND)
            return
        transaction, category, account = row
        error = await apply(session, transaction, category, account)
        if error:
            await message.answer(error)
            return
        # текст собираем до commit: после него объекты устаревают
        text = card_text(transaction, category, account)
        keyboard = card_keyboard(transaction)
        await session.commit()
    await state.clear()
    await message.answer(f"{title}\n{text}", reply_markup=keyboard)


@router.message(TransactionEditStates.waiting_for_amount)
async def save_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer("Напиши сумму числом, например: <i>12,5</i>")
        return

    async def apply(session, transaction, category, account):
        try:
            await set_transaction_amount(session, transaction, category.type, amount)
        except exc.InsufficientFunds:
            symbol = CURRENCY_SYMBOLS.get(account.currency, account.currency)
            return not_enough_money_text(account, symbol)
        return None

    await save_edit(message, state, apply, "✅ Сумма изменена")


@router.message(TransactionEditStates.waiting_for_description)
async def save_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if not description or len(description) > DESCRIPTION_MAX:
        await message.answer(f"Напиши описание текстом, до {DESCRIPTION_MAX} символов")
        return

    async def apply(session, transaction, category, account):
        await set_transaction_description(session, transaction, description)

    await save_edit(message, state, apply, "✅ Описание изменено")


@router.message(TransactionEditStates.waiting_for_date)
async def save_date(message: Message, state: FSMContext):
    tr_date = parse_date(message.text or "")
    if tr_date is None:
        await message.answer(
            "Не понял дату. Напиши <i>вчера</i>, <i>05.11</i> или <i>05.11.2026</i>"
        )
        return
    if tr_date > date.today():  # noqa: DTZ011
        await message.answer("Эта дата ещё не наступила. Напиши другую.")
        return

    async def apply(session, transaction, category, account):
        await set_transaction_date(session, transaction, tr_date)

    await save_edit(message, state, apply, "✅ Дата изменена")
