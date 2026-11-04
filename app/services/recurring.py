"""Регулярные операции: в день платежа бот спрашивает, добавить ли операцию.

Раз в сутки в 20:00 по Минску (как вечернее сообщение) ищем платежи с
next_due <= сегодня, по которым вопрос ещё не отправляли, и шлём «Добавить?».
Сама операция создаётся только после нажатия кнопки (handlers/recurring.py).
"""

import asyncio
import calendar
import html
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import CURRENCY_SYMBOLS, TX_TYPES
from app.database import async_session_maker
from app.repositories.recurring_repository import due_payments, mark_prompted
from app.services.reminders import MINSK, SEND_PAUSE_SECONDS, seconds_until_next

logger = logging.getLogger(__name__)


def today_minsk() -> date:
    return datetime.now(MINSK).date()


def schedule_date(day_of_month: int, year: int, month: int) -> date:
    # 31-е в коротком месяце превращается в его последний день
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day_of_month, last))


def next_month(year: int, month: int):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def first_due(day_of_month: int, today: date) -> date:
    # ближайший платёж: в этом месяце, если день ещё не прошёл, иначе в следующем
    this_month = schedule_date(day_of_month, today.year, today.month)
    if this_month >= today:
        return this_month
    return schedule_date(day_of_month, *next_month(today.year, today.month))


def next_due_after(day_of_month: int, due: date) -> date:
    return schedule_date(day_of_month, *next_month(due.year, due.month))


def year_due(day: int, month: int, today: date) -> date:
    # ближайший ежегодный платёж: в этом году, если дата не прошла, иначе в следующем.
    # 29.02 в невисокосный год превращается в 28.02
    this_year = schedule_date(day, today.year, month)
    if this_year >= today:
        return this_year
    return schedule_date(day, today.year + 1, month)


def advance_due(payment, due: date) -> date:
    """Следующая дата платежа после due.

    Считаем от запланированной даты, а не от того дня, когда человек нажал
    кнопку: иначе расписание «поплыло» бы от запоздалых ответов.
    """
    if payment.period == "days":
        # 30 дней это не месяц: платёж каждый раз сдвигается на ровно N дней
        return due + timedelta(days=payment.interval_days)
    if payment.period == "year":
        return schedule_date(payment.day_of_month, due.year + 1, payment.anchor_month)
    return next_due_after(payment.day_of_month, due)


def period_text(payment) -> str:
    if payment.period == "days":
        return f"каждые {payment.interval_days} дн."
    if payment.period == "year":
        return f"раз в год, {payment.day_of_month:02d}.{payment.anchor_month:02d}"
    return f"каждый месяц, {payment.day_of_month}-го числа"


def due_token(due: date) -> str:
    return due.strftime("%Y%m%d")


def parse_due_token(token: str) -> date | None:
    try:
        return datetime.strptime(token, "%Y%m%d").date()  # noqa: DTZ007
    except ValueError:
        return None


def payment_label(payment, category_name, currency):
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    name = html.escape(payment.description or category_name)
    return (
        f"<b>{name}</b> {TX_TYPES[payment.tx_type]}{payment.amount} {symbol} → "
        f"{html.escape(category_name)}"
    )


def prompt_text(payment, category_name, currency):
    kind = "Подписка" if payment.tx_type == "expense" else "Регулярный доход"
    return (
        f"🔁 {kind} по расписанию\n"
        f"{payment_label(payment, category_name, currency)}\n"
        f"Дата платежа: {payment.next_due.strftime('%d.%m.%Y')}\n\n"
        "Добавить в историю?"
    )


def prompt_keyboard(payment):
    token = due_token(payment.next_due)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Добавить", callback_data=f"rec:ok:{payment.id}:{token}")
    builder.button(text="⏭ Пропустить", callback_data=f"rec:skip:{payment.id}:{token}")
    builder.adjust(2)
    return builder.as_markup()


async def send_recurring_prompts(bot: Bot, today: date | None = None) -> int:
    today = today or today_minsk()
    # сначала читаем всё и закрываем сессию: рассылка идёт с паузами
    async with async_session_maker() as session:
        rows = [
            (
                payment.id,
                payment.next_due,
                telegram_id,
                prompt_text(payment, category_name, currency),
                prompt_keyboard(payment),
            )
            for payment, telegram_id, category_name, currency in await due_payments(
                session, today
            )
        ]
    sent = 0
    for payment_id, due, telegram_id, text, keyboard in rows:
        try:
            await bot.send_message(telegram_id, text, reply_markup=keyboard)
        except TelegramAPIError:
            # не отправилось (например, бота заблокировали): попробуем завтра
            logger.exception("Could not send recurring prompt %s", payment_id)
            continue
        sent += 1
        async with async_session_maker() as session:
            await mark_prompted(session, payment_id, due)
            await session.commit()
        await asyncio.sleep(SEND_PAUSE_SECONDS)
    logger.info("Recurring prompts sent: %s", sent)
    return sent


async def recurring_loop(bot: Bot):
    # живёт всё время работы бота, как reminder_loop; если бот был выключен
    # в 20:00, вопрос придёт на следующий вечер (next_due <= сегодня)
    while True:
        await asyncio.sleep(seconds_until_next(datetime.now(MINSK)))
        try:
            await send_recurring_prompts(bot)
        except Exception:
            logger.exception("Recurring prompts failed")
