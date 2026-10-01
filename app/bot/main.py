import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from dotenv import load_dotenv

from app.bot.handlers.add_category import router as add_category_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.transaction import router as add_transaction_router

load_dotenv()
bot_token = os.getenv("BOT_TOKEN")

bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
dp.include_router(start_router)
dp.include_router(add_category_router)
dp.include_router(add_transaction_router)

commands = [
    BotCommand(command="start", description="Начать работу с ботом"),
    BotCommand(command="add_category", description="Добавить свою категорию"),
]


async def main():
    await bot.set_my_commands(commands)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
