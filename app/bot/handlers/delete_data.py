from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import DeleteDataStates
from app.bot.texts import DATA_DELETED_TEXT, delete_data_warning
from app.database import async_session_maker
from app.repositories.user_repository import (
    count_user_data,
    delete_user_data,
    get_user,
)

router = Router()


@router.message(Command("delete_my_data"), StateFilter("*"))
async def cmd_delete_my_data(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        # get_user, а не get_or_create_user: незнакомому человеку запись не создаём
        user = await get_user(session, message.from_user.id)
        if user is None:
            await message.answer("У меня нет твоих данных, удалять нечего.")
            return
        counts = await count_user_data(session, user.id)
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Да, удалить всё навсегда", callback_data="deldata:confirm")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    await message.answer(delete_data_warning(counts), reply_markup=builder.as_markup())
    await state.set_state(DeleteDataStates.waiting_for_confirm)


@router.callback_query(
    F.data == "deldata:confirm", DeleteDataStates.waiting_for_confirm
)
async def confirm_delete_data(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # первым делом: повторное нажатие уже не найдёт состояние
    async with async_session_maker() as session:
        # удаляем по Telegram id того, кто нажал: id пользователя из кнопки не берём
        user = await get_user(session, callback.from_user.id)
        if user is not None:
            await delete_user_data(session, user.id)
            await session.commit()
    await callback.message.edit_text(DATA_DELETED_TEXT)
    await callback.answer()


@router.callback_query(F.data == "deldata:confirm")
async def old_confirm_callback(callback: CallbackQuery):
    # кнопка из старого сообщения (состояния уже нет): ничего не удаляем
    await callback.answer(
        "Кнопка устарела. Набери /delete_my_data заново", show_alert=True
    )
    await callback.message.edit_reply_markup(reply_markup=None)
