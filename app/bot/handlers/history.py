from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.constants import CURRENCY_SYMBOLS, TX_TYPES
from app.database import async_session_maker
from app.models.user import User
from app.repositories.account_repository import get_account
from app.repositories.user_repository import get_or_create_user
from app.repositories.transaction_repository import get_recent_transactions
router = Router()

@router.message(Command("history"))
async def get_recent_transactions_h(message: Message):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        if user.active_account_id is None:
            await message.answer("У тебя ещё нет счёта. Набери /start")
            return
        account = await get_account(session, user.active_account_id)
        currency_symbol = CURRENCY_SYMBOLS[account.currency]
        has_more, transactions = await get_recent_transactions(session, user.active_account_id, offset=0)
        if len(transactions) == 0:
            await message.answer("Пока нет операций")
            return
        text_list = ["Вот твои последние 10 операций\n"]
        for transaction, category_name, category_type in transactions:
            tx_type = TX_TYPES[category_type]
            text_list.append(f"{transaction.date.strftime("%d.%m")} {category_name} {transaction.description or ""} {tx_type}{transaction.amount}{currency_symbol}")
        text = "\n".join(text_list)
        await message.answer(text)