from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.repositories.account_repository import get_account
from app.repositories.transaction_repository import get_stats
from app.repositories.user_repository import get_or_create_user

router = Router()


@router.message(Command("stats"))
async def show_stats(message: Message):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        if user.active_account_id is None:
            await message.answer(
                "❌ У тебя ещё нет счёта. Набери /start, чтобы создать его."
            )
            return
        stats = await get_stats(
            session, user.active_account_id, date.today()  # noqa: DTZ011
        )
        if not stats:
            await message.answer("У вас еще нет расходов за этот месяц")
            return
        account = await get_account(session, user.active_account_id)
        currency_symbol = CURRENCY_SYMBOLS[account.currency]
        lines = []
        for name, amount in stats:
            lines.append(f"{name}: {amount} {currency_symbol}")
        text = "\n".join(lines)
        total = sum(amount for _, amount in stats)
        await message.answer(f"Расходы:\n\n{text}\n\nИтого: {total} {currency_symbol}")
