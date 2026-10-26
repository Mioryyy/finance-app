import html
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import exceptions as exc
from app.bot.states import TransferStates
from app.bot.texts import account_label
from app.constants import ACCOUNT_TYPES_EMOJI, CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.parsing import parse_amount
from app.repositories.account_repository import (
    get_account,
    get_accounts_for_user,
    get_user_account,
)
from app.repositories.transfer_repository import create_transfer
from app.repositories.user_repository import get_or_create_user

router = Router()

ERROR_TEXTS = {
    exc.ForeignAccount: "Неверный счёт",
    exc.SameAccount: "Счёт получателя совпадает со счётом отправителя",
    exc.DifferentCurrency: "Валюты счетов не совпадают",
    exc.InvalidAmount: "Некорректная сумма",
    exc.InsufficientFunds: "Недостаточно средств",
}


async def build_accounts_page(telegram_id, account_currency):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        accounts = await get_accounts_for_user(session, user.id)
        text_list = ["Вот твои счета"]
        counter_acc = 0
        for account in accounts:
            if account_currency == account.currency:
                if account.id == user.active_account_id:
                    parts = ["✅"]
                else:
                    parts = []
                parts.extend(
                    [
                        ACCOUNT_TYPES_EMOJI[account.type],
                        html.escape(account.name),
                        "—",
                        str(account.balance),
                        CURRENCY_SYMBOLS[account.currency],
                    ]
                )
                text = " ".join(p for p in parts if p)
                text_list.append(text)
                counter_acc += 1
        if counter_acc <= 1:
            return "Нет других счетов в этой валюте", None
        builder = InlineKeyboardBuilder()
        for account in accounts:
            if (
                account.id != user.active_account_id
                and account_currency == account.currency
            ):
                builder.button(
                    text=f"{account.name}", callback_data=f"acctransf:{account.id}"
                )
        builder.adjust(1)
        keyboard = builder.as_markup()
        text = "\n".join(text_list)
        return text, keyboard


@router.message(Command("transfer"))
async def start_transfer_creation(message: Message, state: FSMContext):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        account = await get_user_account(session, user.active_account_id, user.id)
        if account is None:
            await message.answer("Счёт не найден")
            return
    await state.update_data(account_from_id=account.id)
    message_txt, keyboard = await build_accounts_page(
        message.from_user.id, account.currency
    )
    if not keyboard:
        await message.answer(message_txt)
        await state.clear()
        return
    currency_symbol = CURRENCY_SYMBOLS[account.currency]
    await message.answer(
        f"Перевод со счёта {account_label(account)} "
        f"(баланс {account.balance} {currency_symbol})\n"
        "Сменить счёт-источник: /accounts\n\n"
        f"На какой счёт перевести?\n{message_txt}",
        reply_markup=keyboard,
    )
    await state.set_state(TransferStates.waiting_for_to_account)


@router.callback_query(
    F.data.startswith("acctransf:"), TransferStates.waiting_for_to_account
)
async def process_transfer_creation(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        account = await get_user_account(session, account_id, user.id)
        if account is None:
            await callback.answer("Счёт не найден", show_alert=True)
            return
    await state.update_data(account_to_id=account.id)
    await state.set_state(TransferStates.waiting_for_amount)
    data = await state.get_data()
    account_from_id = data["account_from_id"]
    async with async_session_maker() as session:
        account_from = await get_account(session, account_from_id)
    await callback.message.edit_text(
        f"Введите сумму перевода\nДоступно: {account_from.balance}{CURRENCY_SYMBOLS[account_from.currency]}"
    )
    await callback.answer()


@router.message(TransferStates.waiting_for_amount)
async def ask_confirmation(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer("Введи сумму числом, например 150 или 10.50")
        return
    data = await state.get_data()
    async with async_session_maker() as session:
        account_from = await get_account(session, data["account_from_id"])
        account_to = await get_account(session, data["account_to_id"])
    await state.update_data(amount=str(amount))
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data="transfer:accept")
    builder.button(text="❌ Отмена", callback_data="transfer:cancel")
    builder.adjust(2)
    await message.answer(
        f"Подтверждаете перевод {amount} {CURRENCY_SYMBOLS[account_from.currency]}\n"
        f"Со счёта {html.escape(account_from.name)} "
        f"на счёт {html.escape(account_to.name)}?",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(TransferStates.waiting_for_accept)


@router.callback_query(TransferStates.waiting_for_accept, F.data == "transfer:cancel")
async def cancel_transfer(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Перевод отменён")
    await callback.answer()


@router.callback_query(TransferStates.waiting_for_accept, F.data == "transfer:accept")
async def confirm_transfer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()  # первым делом: второй клик уже не найдёт состояние
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        try:
            await create_transfer(
                session,
                user.id,
                data["account_from_id"],
                data["account_to_id"],
                Decimal(data["amount"]),
            )
        except exc.TransferError as e:
            text = ERROR_TEXTS.get(type(e), "Не удалось выполнить перевод")
            await callback.message.edit_text(f"❌ Ошибка\n{text}")
            await callback.answer()
            return
        await session.commit()
    await callback.message.edit_text("Перевод прошёл успешно")
    await callback.answer()
