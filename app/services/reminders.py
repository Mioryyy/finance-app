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
)
from app.database import async_session_maker
from app.repositories.transaction_repository import (
    count_transactions_on,
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


def evening_message(review_rows, today_count):
    builder = InlineKeyboardBuilder()
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
        text = "\n".join(lines)
        count = len(review_rows)
        rows = [5] * (count // 5) + ([count % 5] if count % 5 else [])
    else:
        if today_count:
            text = (
                f"📒 Сегодня записано операций: {today_count}. Ничего не забыл?\n"
                "Напиши трату, например: <i>кофе 5</i>"
            )
        else:
            text = (
                "📒 Сегодня ещё нет записей. Были траты?\n"
                "Напиши, например: <i>кофе 5</i>"
            )
        rows = []
    builder.button(text="🔕 Не напоминать", callback_data="remind:off")
    builder.adjust(*rows, 1)
    return text, builder.as_markup()


async def send_evening_messages(bot: Bot) -> int:
    today = datetime.now(MINSK).date()
    # сначала собираем всё из базы и закрываем сессию: рассылка может идти долго
    messages = []
    async with async_session_maker() as session:
        for user in await get_users_for_reminders(session):
            review_rows = await get_review_transactions(
                session, user.id, REVIEW_LIST_LIMIT
            )
            today_count = await count_transactions_on(session, user.id, today)
            messages.append(
                (user.id, user.telegram_id, *evening_message(review_rows, today_count))
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
