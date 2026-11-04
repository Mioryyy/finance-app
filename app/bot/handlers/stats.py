import calendar
import html
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.parsing import parse_period_month
from app.repositories.transaction_repository import category_summary
from app.repositories.user_repository import get_or_create_user

router = Router()

MONTHS = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)

STATS_USAGE = (
    "Не понял период. Варианты:\n"
    "/stats — этот месяц\n"
    "/stats сегодня\n"
    "/stats неделя\n"
    "/stats 09.2026 — конкретный месяц"
)


def month_bounds(day: date):
    first = day.replace(day=1)
    return first, day.replace(day=calendar.monthrange(day.year, day.month)[1])


def resolve_period(arg: str | None, today: date):
    """Период и такой же отрезок до него для сравнения.

    Возвращает (название, начало, конец, начало прошлого, конец прошлого,
    как назвать прошлый период) или None, если аргумент непонятен.
    Текущий период сравниваем с тем же числом дней прошлого: на 10-е число
    месяца это первые 10 дней прошлого месяца, а не весь месяц.
    """
    arg = (arg or "").strip().lower()
    if arg in ("сегодня", "день"):
        yesterday = today - timedelta(days=1)
        return "Сегодня", today, today, yesterday, yesterday, "вчера"
    if arg == "неделя":
        start = today - timedelta(days=today.weekday())
        prev_start = start - timedelta(days=7)
        prev_end = prev_start + (today - start)
        return "Эта неделя", start, today, prev_start, prev_end, "прошлая неделя"
    if arg:
        month = parse_period_month(arg)
        if month is None:
            return None
    else:
        month = today.replace(day=1)
    start, end = month_bounds(month)
    end = min(end, today)
    prev_start, prev_last = month_bounds(start - timedelta(days=1))
    prev_end = min(prev_last, prev_start + (end - start))
    title = f"{MONTHS[month.month - 1]} {month.year}"
    return title, start, end, prev_start, prev_end, "прошлый месяц"


def change_text(total, prev_total, prev_label, symbol):
    if not prev_total:
        return f"{prev_label.capitalize()}: трат не было"
    percent = round((total - prev_total) / prev_total * 100)
    if percent > 0:
        trend = f"📈 на {percent}% больше"
    elif percent < 0:
        trend = f"📉 на {-percent}% меньше"
    else:
        trend = "без изменений"
    return f"{prev_label.capitalize()}: {prev_total} {symbol} ({trend})"


def stats_text(title, prev_label, expenses, incomes, prev_expenses):
    """Текст /stats. Строки приходят как (валюта, категория, сумма, количество).

    Каждая валюта отдельным блоком: Br и $ складывать нельзя.
    """
    expense_by_currency = {}
    for currency, name, total, _count in expenses:
        expense_by_currency.setdefault(currency, []).append((name, total))
    income_totals = {}
    for currency, _name, total, _count in incomes:
        income_totals[currency] = income_totals.get(currency, 0) + total
    prev_totals = {}
    for currency, _name, total, _count in prev_expenses:
        prev_totals[currency] = prev_totals.get(currency, 0) + total

    currencies = sorted(set(expense_by_currency) | set(income_totals))
    blocks = []
    for currency in currencies:
        symbol = CURRENCY_SYMBOLS.get(currency, currency)
        categories = sorted(
            expense_by_currency.get(currency, []), key=lambda row: (-row[1], row[0])
        )
        total_expense = sum(amount for _, amount in categories)
        total_income = income_totals.get(currency, 0)
        lines = []
        if len(currencies) > 1:
            lines.append(f"<b>{currency}</b>")
        lines.append("<b>Расходы</b>")
        for name, amount in categories:
            percent = round(amount / total_expense * 100)
            lines.append(f"{html.escape(name)}: {amount} {symbol} · {percent}%")
        if not categories:
            lines.append("нет")
        lines += [
            "",
            f"Итого расходов: {total_expense} {symbol}",
            change_text(total_expense, prev_totals.get(currency), prev_label, symbol),
            f"Доходы: {total_income} {symbol}",
            f"Разница: {total_income - total_expense:+} {symbol}",
        ]
        blocks.append("\n".join(lines))
    return f"📊 <b>{title}</b>\n\n" + "\n\n".join(blocks)


@router.message(Command("stats"))
async def show_stats(message: Message):
    parts = message.text.split()
    period = resolve_period(parts[1] if len(parts) > 1 else None, date.today())  # noqa: DTZ011
    if period is None:
        await message.answer(STATS_USAGE)
        return
    title, start, end, prev_start, prev_end, prev_label = period
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        if user.active_account_id is None:
            await message.answer(
                "❌ У тебя ещё нет счёта. Набери /start, чтобы создать его."
            )
            return
        expenses = await category_summary(session, user.id, start, end, "expense")
        incomes = await category_summary(session, user.id, start, end, "income")
        prev_expenses = await category_summary(
            session, user.id, prev_start, prev_end, "expense"
        )
    if not expenses and not incomes:
        await message.answer(f"📊 <b>{title}</b>\n\nЗа этот период операций нет")
        return
    await message.answer(
        stats_text(title, prev_label, expenses, incomes, prev_expenses)
    )
