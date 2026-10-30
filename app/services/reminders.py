"""Вечернее сообщение в 20:00 по Минску.

Если есть траты, сохранённые быстрым вводом с неуверенной категорией, —
список «проверь». Иначе — короткое напоминание записать траты за день.
Получают только те, у кого есть счёт и не выключены напоминания (/settings).
"""

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import (
    CURRENCY_SYMBOLS,
    MINSK_UTC_OFFSET_HOURS,
    REMINDER_HOUR,
    REVIEW_LIST_LIMIT,
    TX_TYPES,
    WEEKLY_TOP_CATEGORIES,
)
from app.database import async_session_maker
from app.repositories.transaction_repository import (
    count_transactions_on,
    expense_summary,
    get_review_transactions,
)
from app.repositories.user_repository import disable_reminders, get_users_for_reminders

logger = logging.getLogger(__name__)

# в Беларуси нет перехода на летнее время, поэтому хватает фиксированного смещения
MINSK = timezone(timedelta(hours=MINSK_UTC_OFFSET_HOURS), "Europe/Minsk")

# пауза между сообщениями: Telegram ограничивает частоту рассылки
SEND_PAUSE_SECONDS = 0.05


def seconds_until_next(now: datetime) -> float:
    now = now.astimezone(MINSK)
    target = now.replace(hour=REMINDER_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def plural_spendings(count: int) -> str:
    # 1 трата, 2 траты, 5 трат, 11 трат, 21 трата
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} трату"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} траты"
    return f"{count} трат"


def weekly_summary_text(this_week, last_week_totals):
    """Итог недели по расходам; None, если за неделю трат не было.

    this_week — строки (валюта, категория, сумма, количество);
    last_week_totals — {валюта: сумма} за прошлую неделю.
    Каждая валюта отдельно: Br и $ складывать нельзя.
    """
    if not this_week:
        return None
    by_currency = {}
    for currency, category, total, count in this_week:
        by_currency.setdefault(currency, []).append((total, count, category))
    blocks = []
    for currency, categories in sorted(by_currency.items()):
        symbol = CURRENCY_SYMBOLS.get(currency, currency)
        categories.sort(key=lambda row: (-row[0], row[2]))
        total = sum(row[0] for row in categories)
        count = sum(row[1] for row in categories)
        top_total, _, top_name = categories[0]
        lines = [
            f"<b>{total} {symbol}</b> на {plural_spendings(count)}",
            f"Больше всего: {html.escape(top_name)} — {top_total} {symbol}",
        ]
        rest = categories[1:WEEKLY_TOP_CATEGORIES]
        if rest:
            lines.append(
                "Дальше: "
                + ", ".join(
                    f"{html.escape(name)} — {amount} {symbol}"
                    for amount, _, name in rest
                )
            )
        if currency in last_week_totals:
            lines.append(f"Прошлая неделя: {last_week_totals[currency]} {symbol}")
        blocks.append("\n".join(lines))
    return "📊 <b>Итог недели</b>\n" + "\n\n".join(blocks)


def evening_message(review_rows, today_count, weekly_text=None):
    builder = InlineKeyboardBuilder()
    parts = []
    if weekly_text:
        parts.append(weekly_text)
    rows = []
    if review_rows:
        lines = ["🔎 <b>Проверь траты</b>, в которых я не уверен в категории:\n"]
        for number, (transaction, category_name, category_type, currency) in enumerate(
            review_rows, start=1
        ):
            symbol = CURRENCY_SYMBOLS.get(currency, currency)
            lines.append(
                f"{number}. {transaction.date.strftime('%d.%m')} "
                f"{html.escape(transaction.description or 'без описания')} "
                f"{TX_TYPES[category_type]}{transaction.amount} {symbol} → "
                f"{html.escape(category_name)}"
            )
            builder.button(
                text=f"✏️ {number}", callback_data=f"tx:show:{transaction.id}"
            )
        lines.append("\nНажми номер, чтобы открыть трату")
        parts.append("\n".join(lines))
        count = len(review_rows)
        rows = [5] * (count // 5) + ([count % 5] if count % 5 else [])
    if not parts:
        # ни итога недели, ни трат на проверку: обычное напоминание
        if today_count:
            parts.append(
                f"📒 Сегодня записано операций: {today_count}. Ничего не забыл?\n"
                "Напиши трату, например: <i>кофе 5</i>"
            )
        else:
            parts.append(
                "📒 Сегодня ещё нет записей. Были траты?\n"
                "Напиши, например: <i>кофе 5</i>"
            )
    builder.button(text="🔕 Не напоминать", callback_data="remind:off")
    builder.adjust(*rows, 1)
    return "\n\n".join(parts), builder.as_markup()


async def weekly_text_for(session, user_id, today):
    # неделя — с понедельника по сегодняшнее воскресенье включительно
    week_start = today - timedelta(days=today.weekday())
    this_week = await expense_summary(session, user_id, week_start, today)
    last_week = await expense_summary(
        session, user_id, week_start - timedelta(days=7), week_start - timedelta(days=1)
    )
    last_week_totals = {}
    for currency, _category, total, _count in last_week:
        last_week_totals[currency] = last_week_totals.get(currency, 0) + total
    return weekly_summary_text(this_week, last_week_totals)


async def send_evening_messages(bot: Bot, today=None) -> int:
    # today можно передать в тестах, чтобы проверить воскресенье
    if today is None:
        today = datetime.now(MINSK).date()
    is_sunday = today.weekday() == 6
    # сначала собираем всё из базы и закрываем сессию: рассылка может идти долго
    messages = []
    async with async_session_maker() as session:
        for user in await get_users_for_reminders(session):
            review_rows = await get_review_transactions(
                session, user.id, REVIEW_LIST_LIMIT
            )
            today_count = await count_transactions_on(session, user.id, today)
            weekly = (
                await weekly_text_for(session, user.id, today) if is_sunday else None
            )
            messages.append(
                (
                    user.id,
                    user.telegram_id,
                    *evening_message(review_rows, today_count, weekly),
                )
            )
    sent = 0
    blocked = []
    for user_id, telegram_id, text, keyboard in messages:
        try:
            await bot.send_message(telegram_id, text, reply_markup=keyboard)
            sent += 1
        except TelegramForbiddenError:
            # человек заблокировал бота: больше не пытаемся каждый вечер
            blocked.append(user_id)
        except TelegramAPIError:
            logger.exception("Could not send the evening message to user %s", user_id)
        await asyncio.sleep(SEND_PAUSE_SECONDS)
    if blocked:
        async with async_session_maker() as session:
            await disable_reminders(session, blocked)
            await session.commit()
    logger.info("Evening messages sent: %s, blocked: %s", sent, len(blocked))
    return sent


async def reminder_loop(bot: Bot):
    # живёт всё время работы бота; если бот перезапустился после 20:00,
    # сегодняшнее сообщение пропускается, а не уходит второй раз
    while True:
        await asyncio.sleep(seconds_until_next(datetime.now(MINSK)))
        try:
            await send_evening_messages(bot)
        except Exception:
            # ошибка одного вечера не должна остановить напоминания навсегда
            logger.exception("Evening messages failed")
