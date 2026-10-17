import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import CURRENCY_SYMBOLS, TX_TYPES
from app.database import async_session_maker
from app.repositories.account_repository import get_account
from app.repositories.transaction_repository import get_recent_transactions
from app.repositories.user_repository import get_or_create_user

router = Router()

async def build_history_page(telegram_id, page):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        if user.active_account_id is None:
            return "У тебя ещё нет счёта. Набери /start", None
        account = await get_account(session, user.active_account_id)
        currency_symbol = CURRENCY_SYMBOLS[account.currency]
        has_more, transactions = await get_recent_transactions(session, user.active_account_id, page)
        if len(transactions) == 0:
            return "Пока нет операций", None
        text_list = ["Вот твои последние операции\n"]
        for transaction, category_name, category_type in transactions:
            tx_type = TX_TYPES[category_type]
            parts = [transaction.date.strftime("%d.%m"),
                     html.escape(category_name),
                     html.escape(transaction.description or ""),
                     f"{tx_type}{transaction.amount}{currency_symbol}"]
            text = " ".join(p for p in parts if p)
            text_list.append(text)
        text = "\n".join(text_list)
        if page == 0 and not has_more:
            return text, None
        builder = InlineKeyboardBuilder()
        if page > 0:
            builder.button(text = "⬅️ Назад", callback_data = f"history:{page - 1}")
        if has_more:
            builder.button(text="Вперёд ➡️", callback_data=f"history:{page + 1}")
        builder.adjust(2)
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