import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from dotenv import load_dotenv

from app.bot.handlers.account_edit import router as account_edit_router
from app.bot.handlers.accounts import router as accounts_router
from app.bot.handlers.add_category import router as add_category_router
from app.bot.handlers.cancel import router as cancel_router
from app.bot.handlers.delete_data import router as delete_data_router
from app.bot.handlers.feedback import router as feedback_router
from app.bot.handlers.help import router as help_router
from app.bot.handlers.history import router as history_router
from app.bot.handlers.review import router as review_router
from app.bot.handlers.settings import router as settings_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.stats import router as stats_router
from app.bot.handlers.transaction import router as add_transaction_router
from app.bot.handlers.transfer import router as transfer_router
from app.services.reminders import reminder_loop

load_dotenv()
bot_token = os.getenv("BOT_TOKEN")

bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
dp.include_router(cancel_router)
dp.include_router(help_router)
# раньше остальных: команда должна сработать и посреди любого диалога
dp.include_router(delete_data_router)
dp.include_router(feedback_router)
dp.include_router(settings_router)
dp.include_router(review_router)
dp.include_router(account_edit_router)
dp.include_router(accounts_router)
dp.include_router(transfer_router)
dp.include_router(start_router)
dp.include_router(history_router)
dp.include_router(add_category_router)
dp.include_router(stats_router)
dp.include_router(add_transaction_router)


commands = [
    BotCommand(command="history", description="Последние операции"),
    BotCommand(command="stats", description="Расходы по категориям за месяц"),
    BotCommand(command="accounts", description="Счета и балансы"),
    BotCommand(command="transfer", description="Перевод между своими счетами"),
    BotCommand(command="add_category", description="Добавить свою категорию"),
    BotCommand(command="create_account", description="Создать новый счёт"),
    BotCommand(command="help", description="Как пользоваться ботом"),
    BotCommand(command="settings", description="Быстрый ввод и напоминания"),
    BotCommand(command="feedback", description="Написать автору"),
    BotCommand(command="delete_my_data", description="Удалить все мои данные"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
    BotCommand(command="start", description="Начать заново"),
]


async def main():
    await bot.set_my_commands(commands)
    # вечернее сообщение в 20:00 работает рядом с polling; ссылку держим,
    # иначе задачу может собрать сборщик мусора
    reminder_task = asyncio.create_task(reminder_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()


if __name__ == "__main__":
    # без этого aiogram пишет в лог только ошибки, и по `docker compose logs`
    # не видно, запустился ли polling и приходят ли сообщения
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
