"""Команды только для автора бота (чат ADMIN_CHAT_ID)."""

from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.handlers.feedback import admin_chat_id
from app.constants import FUNNEL_DAYS, MINSK_TZ_NAME
from app.database import async_session_maker
from app.repositories.user_repository import funnel_by_day, funnel_total
from app.services.reminders import MINSK

router = Router()


def from_admin(message: Message) -> bool:
    # остальным команда «не существует»: сообщение уйдёт дальше,
    # и бот ответит как на любую незнакомую команду
    return message.chat.id == admin_chat_id()


def funnel_table(rows, total) -> str:
    lines = ["дата    пришли счёт 1-я 2+"]
    for day, came, account, first, repeat in rows:
        lines.append(f"{day:%d.%m} {came:>8} {account:>4} {first:>3} {repeat:>2}")
    if not rows:
        lines.append("за эти дни никто не пришёл")
    came, account, first, repeat = total
    lines.append(f"всего {came:>8} {account:>4} {first:>3} {repeat:>2}")
    return "\n".join(lines)


@router.message(Command("funnel"), from_admin)
async def cmd_funnel(message: Message):
    since = datetime.now(MINSK) - timedelta(days=FUNNEL_DAYS)
    async with async_session_maker() as session:
        rows = await funnel_by_day(session, since, MINSK_TZ_NAME)
        total = await funnel_total(session)
    await message.answer(
        f"📈 Воронка за {FUNNEL_DAYS} дней по дате регистрации\n"
        f"<pre>{funnel_table(rows, total)}</pre>\n"
        "«всего» — все пользователи, в том числе пришедшие до появления даты"
    )
