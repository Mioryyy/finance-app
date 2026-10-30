from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import REMINDERS_OFF_TEXT, SETTINGS_TEXT
from app.database import async_session_maker
from app.repositories.user_repository import (
    SETTINGS,
    get_or_create_user,
    toggle_setting,
)

router = Router()


def settings_keyboard(quick_entry: bool, reminders: bool):
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⚡ Быстрый ввод: {'вкл' if quick_entry else 'выкл'}",
        callback_data="settings:quick_entry",
    )
    builder.button(
        text=f"🔔 Напоминание в 20:00: {'вкл' if reminders else 'выкл'}",
        callback_data="settings:reminders",
    )
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("settings"), StateFilter("*"))
async def cmd_settings(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, message.from_user.id)
        flags = user.quick_entry, user.reminders
        await session.commit()
    await message.answer(SETTINGS_TEXT, reply_markup=settings_keyboard(*flags))


@router.callback_query(F.data.startswith("settings:"))
async def toggle(callback: CallbackQuery):
    name = callback.data.split(":", 1)[1]
    if name not in SETTINGS:
        await callback.answer("Кнопка устарела, набери /settings", show_alert=True)
        return
    # настройки меняем только себе: пользователь — тот, кто нажал кнопку
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        await toggle_setting(session, user, name)
        flags = user.quick_entry, user.reminders
        await session.commit()
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(*flags))
    await callback.answer("Сохранено")


@router.callback_query(F.data == "remind:off")
async def reminders_off(callback: CallbackQuery):
    # кнопка «Не напоминать» под вечерним сообщением
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        if user.reminders:
            await toggle_setting(session, user, "reminders")
        await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(REMINDERS_OFF_TEXT)
    await callback.answer()
