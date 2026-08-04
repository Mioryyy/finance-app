import asyncio
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from app.bot.handlers.add_category import router as add_category_router
from app.bot.handlers.expense import router as add_expense_router
from app.bot.handlers.start import router as start_router

load_dotenv()
bot_token = os.getenv("BOT_TOKEN")

bot = Bot(token=bot_token)
dp = Dispatcher()
dp.include_router(start_router)
dp.include_router(add_category_router)
dp.include_router(add_expense_router)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
