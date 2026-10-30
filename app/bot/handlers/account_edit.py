"""Правка счёта кнопками: название, тип, стартовый остаток.

Кнопки появляются под сообщением о созданном при /start счёте. В каждой
кнопке id счёта, и ему не доверяем: счёт ищем только среди своих.
"""

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import exceptions as exc
from app.bot.states import AccountEditStates
from app.bot.texts import (
    ACCOUNT_NAME_MAX,
    BALANCE_LOCKED_TEXT,
    BALANCE_PROMPT,
    RENAME_PROMPT,
)
from app.constants import ACCOUNT_TYPES, ACCOUNT_TYPES_EMOJI, CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.parsing import parse_amount
from app.repositories.account_repository import (
    account_has_operations,
    get_user_account,
    rename_account,
    set_account_type,
    set_starting_balance,
)
from app.repositories.user_repository import get_or_create_user

router = Router()

NOT_FOUND = "Счёт не найден"


def account_summary(account):
    symbol = CURRENCY_SYMBOLS.get(account.currency, account.currency)
    return (
        f"{ACCOUNT_TYPES_EMOJI[account.type]} <b>{html.escape(account.name)}</b> · "
        f"{account.currency} · баланс {account.balance} {symbol}"
    )


def account_edit_keyboard(account_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data=f"acedit:name:{account_id}")
    builder.button(text="💳 Тип", callback_data=f"acedit:type:{account_id}")
    builder.button(text="💰 Остаток", callback_data=f"acedit:bal:{account_id}")
    builder.adjust(3)
    return builder.as_markup()


async def load_account(session, telegram_id, account_id):
    user, _is_new = await get_or_create_user(session, telegram_id)
    return await get_user_account(session, account_id, user.id)


def account_id_from(callback: CallbackQuery):
    return int(callback.data.split(":")[2])


@router.callback_query(F.data.startswith("acedit:name:"))
async def ask_name(callback: CallbackQuery, state: FSMContext):
    account_id = account_id_from(callback)
    async with async_session_maker() as session:
        account = await load_account(session, callback.from_user.id, account_id)
    if account is None:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await state.set_state(AccountEditStates.waiting_for_name)
    await state.update_data(account_id=account_id)
    await callback.message.answer(RENAME_PROMPT)
    await callback.answer()


@router.message(AccountEditStates.waiting_for_name)
async def receive_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > ACCOUNT_NAME_MAX:
        await message.answer(
            f"Название — текстом, от 1 до {ACCOUNT_NAME_MAX} символов. Попробуй ещё раз"
        )
        return
    data = await state.get_data()
    await state.clear()
    async with async_session_maker() as session:
        account = await load_account(session, message.from_user.id, data["account_id"])
        if account is None:
            await message.answer(NOT_FOUND)
            return
        await rename_account(session, account, name)
        text = f"✅ Название изменено\n{account_summary(account)}"
        await session.commit()
    await message.answer(text, reply_markup=account_edit_keyboard(data["account_id"]))


@router.callback_query(F.data.startswith("acedit:type:"))
async def ask_type(callback: CallbackQuery):
    account_id = account_id_from(callback)
    async with async_session_maker() as session:
        account = await load_account(session, callback.from_user.id, account_id)
    if account is None:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for account_type, label in ACCOUNT_TYPES.items():
        builder.button(
            text=label, callback_data=f"acedit:settype:{account_id}:{account_type}"
        )
    builder.button(text="⬅️ Назад", callback_data=f"acedit:back:{account_id}")
    builder.adjust(3, 1)
    await callback.message.edit_text(
        f"{account_summary(account)}\n\nВыбери тип счёта",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acedit:settype:"))
async def set_type(callback: CallbackQuery):
    account_id = account_id_from(callback)
    account_type = callback.data.split(":")[3]
    if account_type not in ACCOUNT_TYPES:
        await callback.answer("Кнопка устарела", show_alert=True)
        return
    async with async_session_maker() as session:
        account = await load_account(session, callback.from_user.id, account_id)
        if account is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        try:
            await set_account_type(session, account, account_type)
        except exc.InsufficientFunds:
            await callback.answer(
                "На счёте минус, а наличные и крипта в минус не уходят",
                show_alert=True,
            )
            return
        text = f"✅ Тип изменён\n{account_summary(account)}"
        await session.commit()
    await callback.message.edit_text(
        text, reply_markup=account_edit_keyboard(account_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acedit:back:"))
async def back(callback: CallbackQuery):
    account_id = account_id_from(callback)
    async with async_session_maker() as session:
        account = await load_account(session, callback.from_user.id, account_id)
    if account is None:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.message.edit_text(
        account_summary(account), reply_markup=account_edit_keyboard(account_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acedit:bal:"))
async def ask_balance(callback: CallbackQuery, state: FSMContext):
    account_id = account_id_from(callback)
    async with async_session_maker() as session:
        account = await load_account(session, callback.from_user.id, account_id)
        locked = account is not None and await account_has_operations(
            session, account_id
        )
    if account is None:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    if locked:
        await callback.answer(BALANCE_LOCKED_TEXT, show_alert=True)
        return
    await state.set_state(AccountEditStates.waiting_for_balance)
    await state.update_data(account_id=account_id)
    await callback.message.answer(BALANCE_PROMPT)
    await callback.answer()


@router.message(AccountEditStates.waiting_for_balance)
async def receive_balance(message: Message, state: FSMContext):
    amount = parse_amount((message.text or "").strip())
    if amount is None:
        await message.answer("Напиши сумму числом больше нуля, например: 250")
        return
    data = await state.get_data()
    await state.clear()
    async with async_session_maker() as session:
        account = await load_account(session, message.from_user.id, data["account_id"])
        if account is None:
            await message.answer(NOT_FOUND)
            return
        try:
            # проверяем ещё раз: между кнопкой и суммой могла появиться трата
            await set_starting_balance(session, account, amount)
        except exc.AccountHasOperations:
            await message.answer(BALANCE_LOCKED_TEXT)
            return
        text = f"✅ Остаток записан\n{account_summary(account)}"
        await session.commit()
    await message.answer(text, reply_markup=account_edit_keyboard(data["account_id"]))
