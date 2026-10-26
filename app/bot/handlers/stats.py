import html
from datetime import date, datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.texts import account_label
from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.repositories.account_repository import get_account
from app.repositories.transaction_repository import get_stats
from app.repositories.user_repository import get_or_create_user

router = Router()


@router.message(Command("stats"))
async def show_stats(message: Message):
    try:
        parts = message.text.split()
        if len(parts) > 1:
            period_str = parts[1]
            period = datetime.strptime(period_str, "%m.%Y").date()  # noqa: DTZ007
        else:
            period = date.today()  # noqa: DTZ011
    except ValueError:
        await message.answer("Напиши команду в формате /stats мм.гггг")
        return
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        if user.active_account_id is None:
            await message.answer(
                "❌ У тебя ещё нет счёта. Набери /start, чтобы создать его."
            )
            return
        account = await get_account(session, user.active_account_id)
        expenses = await get_stats(session, account.id, period, "expense")
        incomes = await get_stats(session, account.id, period, "income")
        header = f"📊 {account_label(account)} · {period.strftime('%m.%Y')}"
        if not expenses and not incomes:
            await message.answer(f"{header}\n\nЗа этот месяц операций нет")
            return
        currency_symbol = CURRENCY_SYMBOLS[account.currency]
    lines = [header, "", "<b>Расходы</b>"]
    for name, amount in expenses:
        lines.append(f"{html.escape(name)}: {amount} {currency_symbol}")
    if not expenses:
        lines.append("нет")
    total_expense = sum(amount for _, amount in expenses)
    total_income = sum(amount for _, amount in incomes)
    lines += [
        "",
        f"Итого расходов: {total_expense} {currency_symbol}",
        f"Доходы: {total_income} {currency_symbol}",
        f"Разница: {total_income - total_expense:+} {currency_symbol}",
    ]
    await message.answer("\n".join(lines))
