"""Лимиты на категории расходов: /limits.

Лимит задаётся на месяц в валюте активного счёта. Предупреждения (80% и
превышение) приходят после записи траты, их считает app/services/limits.py.
"""

from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import LimitStates
from app.constants import CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.parsing import parse_amount
from app.repositories.account_repository import get_account
from app.repositories.category_repository import (
    get_categories_for_user,
    get_user_category,
)
from app.repositories.limit_repository import (
    delete_limit,
    get_user_limits,
    month_spent,
    set_limit,
)
from app.repositories.user_repository import get_or_create_user
from app.services.limits import limit_line

router = Router()

LIMITS_INTRO = (
    "🎯 <b>Лимиты на месяц</b>\n"
    "Задай, сколько готов тратить на категорию, и бот предупредит, когда "
    "потрачено 80% и когда лимит превышен.\n\n"
)
NO_ACCOUNT = "❌ У тебя ещё нет счёта. Набери /start, чтобы создать его."


async def build_limits_page(telegram_id):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        rows = await get_user_limits(session, user.id)
        today = date.today()  # noqa: DTZ011
        lines = []
        builder = InlineKeyboardBuilder()
        for limit, name in rows:
            spent = await month_spent(
                session, user.id, limit.category_id, limit.currency, today
            )
            lines.append(limit_line(name, spent, limit.amount, limit.currency))
            builder.button(text=f"🗑 {name}", callback_data=f"lim:del:{limit.id}")
        await session.commit()
    builder.button(text="➕ Добавить лимит", callback_data="lim:new")
    builder.adjust(1)
    if lines:
        text = LIMITS_INTRO + "\n".join(lines)
    else:
        text = LIMITS_INTRO + "Лимитов пока нет."
    return text, builder.as_markup()


@router.message(Command("limits"), StateFilter("*"))
async def cmd_limits(message: Message, state: FSMContext):
    await state.clear()
    text, keyboard = await build_limits_page(message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "lim:new")
async def choose_category(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        if user.active_account_id is None:
            await callback.answer(NO_ACCOUNT, show_alert=True)
            return
        categories = await get_categories_for_user(session, user.id, "expense")
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(text=category.name, callback_data=f"lim:cat:{category.id}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    await callback.message.answer(
        "На какую категорию поставить лимит?", reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^lim:cat:\d+$"))
async def ask_amount(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        if user.active_account_id is None:
            await callback.answer(NO_ACCOUNT, show_alert=True)
            return
        # id из кнопки не доверяем: категория должна быть доступна пользователю
        category = await get_user_category(session, category_id, user.id, "expense")
        if category is None:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        account = await get_account(session, user.active_account_id)
        category_name, currency = category.name, account.currency
    await state.clear()
    await state.set_state(LimitStates.waiting_for_amount)
    await state.update_data(category_id=category_id, currency=currency)
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    await callback.message.answer(
        f"Сколько можно тратить на {category_name} в месяц? "
        f"Напиши сумму в {symbol}, например: <i>200</i>\nПередумал: /cancel"
    )
    await callback.answer()


@router.message(LimitStates.waiting_for_amount)
async def save_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer("Напиши сумму числом, например: <i>200</i>")
        return
    data = await state.get_data()
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        category = await get_user_category(
            session, data["category_id"], user.id, "expense"
        )
        if category is None:
            await state.clear()
            await message.answer("Категория не найдена")
            return
        await set_limit(session, user.id, category.id, data["currency"], amount)
        await session.commit()
    await state.clear()
    text, keyboard = await build_limits_page(message.from_user.id)
    await message.answer(f"✅ Лимит сохранён\n\n{text}", reply_markup=keyboard)


@router.callback_query(F.data.regexp(r"^lim:del:\d+$"))
async def remove_limit(callback: CallbackQuery):
    limit_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        deleted = await delete_limit(session, limit_id, user.id)
        await session.commit()
    if not deleted:
        await callback.answer("Лимит уже удалён", show_alert=True)
        return
    text, keyboard = await build_limits_page(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Удалено")
