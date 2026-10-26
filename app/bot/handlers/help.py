from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.types import Message

from app.bot.texts import HELP_TEXT

router = Router()


@router.message(Command("help"), StateFilter("*"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)
