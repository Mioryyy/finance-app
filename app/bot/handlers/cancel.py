from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

router = Router()


@router.message(Command("cancel"), StateFilter("*"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено")


@router.callback_query(StateFilter("*"), F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    # редактируем сообщение, чтобы старые кнопки не оставались в чате
    await callback.message.edit_text("Действие отменено")
    await callback.answer()
