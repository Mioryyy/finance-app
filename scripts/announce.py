"""Разовая рассылка объявления об обновлении всем пользователям.

Текст лежит в scripts/announcement.txt и уходит как есть, без разметки.
По умолчанию это сухой прогон: скрипт только показывает текст и считает,
скольким людям он уйдёт. Отправка включается флагом --send.

    docker compose exec bot python -m scripts.announce          # только посмотреть
    docker compose exec bot python -m scripts.announce --send   # отправить

Повторный запуск с --send отправит объявление второй раз, поэтому перед
ним сверьтесь с выводом сухого прогона.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from dotenv import load_dotenv
from sqlalchemy import select

from app.database import async_session_maker
from app.models.user import User
from app.services.reminders import SEND_PAUSE_SECONDS

logger = logging.getLogger(__name__)

TEXT_PATH = Path(__file__).with_name("announcement.txt")


async def send_one(bot: Bot, telegram_id: int, text: str) -> str:
    # возвращает «sent», «blocked» или «failed»
    try:
        await bot.send_message(telegram_id, text, parse_mode=None)
    except TelegramForbiddenError:
        return "blocked"  # человек заблокировал бота
    except TelegramRetryAfter as error:
        # Telegram просит подождать: ждём и пробуем один раз ещё
        await asyncio.sleep(error.retry_after + 1)
        try:
            await bot.send_message(telegram_id, text, parse_mode=None)
        except TelegramAPIError:
            logger.exception("Could not send to %s after retry", telegram_id)
            return "failed"
    except TelegramAPIError:
        logger.exception("Could not send to %s", telegram_id)
        return "failed"
    return "sent"


async def main(send: bool):
    text = TEXT_PATH.read_text(encoding="utf-8").strip()
    async with async_session_maker() as session:
        result = await session.execute(select(User.telegram_id).order_by(User.id))
        telegram_ids = list(result.scalars())
    print(f"Текст объявления:\n\n{text}\n")
    print(f"Получателей в базе: {len(telegram_ids)}")
    if not send:
        print("Сухой прогон: ничего не отправлено. Для отправки добавьте --send")
        return
    load_dotenv()
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    counts = {"sent": 0, "blocked": 0, "failed": 0}
    try:
        for telegram_id in telegram_ids:
            counts[await send_one(bot, telegram_id, text)] += 1
            await asyncio.sleep(SEND_PAUSE_SECONDS)
    finally:
        await bot.session.close()
    print(
        f"Отправлено: {counts['sent']}, заблокировали бота: {counts['blocked']}, "
        f"ошибок: {counts['failed']}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(send="--send" in sys.argv[1:]))
