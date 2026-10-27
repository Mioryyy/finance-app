import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import exceptions as exc
from app.bot.texts import CANT_DELETE_INCOME_TEXT, account_label
from app.constants import CURRENCY_SYMBOLS, TX_TYPES
from app.database import async_session_maker
from app.repositories.account_repository import get_account
from app.repositories.transaction_repository import (
    delete_transaction_by_id,
    get_recent_transactions,
    get_transaction_by_id,
)
from app.repositories.user_repository import get_or_create_user

router = Router()


def format_transaction(transaction, category_name, category_type, currency_symbol):
    tx_type = TX_TYPES[category_type]
    parts = [
        transaction.date.strftime("%d.%m"),
        html.escape(category_name),
        html.escape(transaction.description or ""),
        f"{tx_type}{transaction.amount}{currency_symbol}",
    ]
    text = " ".join(p for p in parts if p)
    return text


async def build_history_page(telegram_id, page):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        if user.active_account_id is None:
            return "У тебя ещё нет счёта. Набери /start", None
        account = await get_account(session, user.active_account_id)
        currency_symbol = CURRENCY_SYMBOLS[account.currency]
        has_more, transactions = await get_recent_transactions(
            session, user.active_account_id, page
        )
        if len(transactions) == 0 and page > 0:
            page -= 1
            has_more, transactions = await get_recent_transactions(
                session, user.active_account_id, page
            )
        header = (
            f"{account_label(account)} · баланс {account.balance} {currency_symbol}"
        )
        if len(transactions) == 0:
            return f"{header}\n\nНа этом счёте пока нет операций", None
        text_list = [f"{header}\n\nПоследние операции:"]
        builder = InlineKeyboardBuilder()
        for number, (transaction, category_name, category_type) in enumerate(
            transactions, start=1
        ):
            text = f"{number}. {format_transaction(transaction, category_name, category_type, currency_symbol)}"
            text_list.append(text)
            builder.button(
                text=f"🗑 {number}", callback_data=f"del:{transaction.id}:{page}"
            )
        text = "\n".join(text_list)
        count = len(transactions)
        adjust = [5] * (count // 5)
        if count % 5 != 0:
            adjust.append(count % 5)
        nav_count = 0
        if page > 0:
            builder.button(text="⬅️ Назад", callback_data=f"history:{page - 1}")
            nav_count += 1
        if has_more:
            builder.button(text="Вперёд ➡️", callback_data=f"history:{page + 1}")
            nav_count += 1
        if nav_count > 0:
            adjust.append(nav_count)
        builder.adjust(*adjust)
        keyboard = builder.as_markup()
        return text, keyboard


@router.message(Command("history"))
async def get_recent_transactions_h(message: Message):
    text, keyboard = await build_history_page(message.from_user.id, 0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("history:"))
async def get_recent_transactions_c(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    text, keyboard = await build_history_page(callback.from_user.id, page)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def callback_delete_request(callback: CallbackQuery):
    _, transaction_id, page = callback.data.split(":")
    transaction_id = int(transaction_id)
    page = int(page)
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        account = await get_account(session, user.active_account_id)
        row = await get_transaction_by_id(
            session, transaction_id, user.active_account_id
        )
    if row is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    transaction, category_name, category_type = row
    currency_symbol = CURRENCY_SYMBOLS[account.currency]
    operation = format_transaction(
        transaction, category_name, category_type, currency_symbol
    )
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да, удалить", callback_data=f"delok:{transaction_id}:{page}"
    )
    builder.button(text="Отмена", callback_data=f"history:{page}")
    keyboard = builder.as_markup()
    await callback.message.edit_text(
        f"Удалить эту операцию?\n{operation}", reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delok:"))
async def callback_delete_confirm(callback: CallbackQuery):
    _, transaction_id, page = callback.data.split(":")
    transaction_id = int(transaction_id)
    page = int(page)
    telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        try:
            deleted = await delete_transaction_by_id(
                session, transaction_id, user.active_account_id
            )
        except exc.InsufficientFunds:
            await callback.answer(CANT_DELETE_INCOME_TEXT, show_alert=True)
            return
        if deleted:
            await session.commit()
        else:
            await callback.answer("Запись уже удалена", show_alert=True)
            return
    text, keyboard = await build_history_page(callback.from_user.id, page)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Удалено")
