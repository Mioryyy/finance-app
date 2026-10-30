"""Карточка уже записанной операции: проверить, сменить категорию, удалить.

Сюда ведут кнопка «✏️ Изменить» после быстрого ввода и вечерний список
«проверь». Кнопки без состояния FSM: работают и через несколько дней.
"""

import html

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import exceptions as exc
from app.bot.texts import CANT_DELETE_INCOME_TEXT, account_label
from app.constants import CURRENCY_SYMBOLS, TX_TYPES
from app.database import async_session_maker
from app.repositories.category_repository import (
    get_categories_for_user,
    get_user_category,
)
from app.repositories.transaction_repository import (
    delete_transaction_by_id,
    get_user_transaction,
    mark_reviewed,
    set_transaction_category,
)
from app.repositories.user_repository import get_or_create_user

router = Router()

NOT_FOUND = "Запись не найдена: возможно, её уже удалили"


def card_text(transaction, category, account):
    currency_symbol = CURRENCY_SYMBOLS.get(account.currency, account.currency)
    text = (
        f"{transaction.date.strftime('%d.%m')} "
        f"<b>{html.escape(transaction.description or '') or 'без описания'}</b> "
        f"{TX_TYPES[category.type]}{transaction.amount} {currency_symbol} → "
        f"{html.escape(category.name)}\n"
        f"{account_label(account)}"
    )
    if transaction.needs_review:
        text += "\n🔎 Проверь категорию"
    return text


def card_keyboard(transaction):
    builder = InlineKeyboardBuilder()
    if transaction.needs_review:
        builder.button(text="✅ Всё верно", callback_data=f"tx:ok:{transaction.id}")
    builder.button(text="🏷 Категория", callback_data=f"tx:cat:{transaction.id}")
    builder.button(text="🗑 Удалить", callback_data=f"tx:del:{transaction.id}")
    if transaction.needs_review:
        builder.adjust(1, 2)
    else:
        builder.adjust(2)
    return builder.as_markup()


async def load(callback: CallbackQuery, session):
    # id операции из кнопки не доверяем: ищем только среди своих счетов
    transaction_id = int(callback.data.split(":")[2])
    user, _is_new = await get_or_create_user(session, callback.from_user.id)
    row = await get_user_transaction(session, transaction_id, user.id)
    return user, row


@router.callback_query(F.data.startswith(("tx:open:", "tx:show:")))
async def open_card(callback: CallbackQuery):
    async with async_session_maker() as session:
        _user, row = await load(callback, session)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        text = card_text(*row)
        keyboard = card_keyboard(row[0])
    if callback.data.startswith("tx:show:"):
        # из вечернего списка: открываем отдельным сообщением, список остаётся
        await callback.message.answer(text, reply_markup=keyboard)
    else:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("tx:ok:"))
async def confirm_category(callback: CallbackQuery):
    async with async_session_maker() as session:
        _user, row = await load(callback, session)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        await mark_reviewed(session, row[0])
        text = card_text(*row)
        await session.commit()
    await callback.message.edit_text(f"✅ Проверено\n{text}")
    await callback.answer()


@router.callback_query(F.data.startswith("tx:cat:"))
async def ask_new_category(callback: CallbackQuery):
    async with async_session_maker() as session:
        user, row = await load(callback, session)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        transaction, category, _account = row
        # тип не меняем: расход остаётся расходом, баланс не трогаем
        categories = await get_categories_for_user(session, user.id, category.type)
        builder = InlineKeyboardBuilder()
        for option in categories:
            builder.button(
                text=option.name,
                callback_data=f"tx:set:{transaction.id}:{option.id}",
            )
        builder.button(text="⬅️ Назад", callback_data=f"tx:open:{transaction.id}")
        builder.adjust(2)
        text = card_text(*row)
    await callback.message.edit_text(
        f"{text}\n\nВыбери категорию", reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tx:set:"))
async def set_category(callback: CallbackQuery):
    category_id = int(callback.data.split(":")[3])
    async with async_session_maker() as session:
        user, row = await load(callback, session)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        transaction, old_category, account = row
        # категория из кнопки: своя или общая и того же типа
        category = await get_user_category(
            session, category_id, user.id, old_category.type
        )
        if category is None:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        await set_transaction_category(session, transaction, category.id)
        text = card_text(transaction, category, account)
        await session.commit()
    await callback.message.edit_text(f"✅ Категория изменена\n{text}")
    await callback.answer()


@router.callback_query(F.data.startswith("tx:del:"))
async def ask_delete(callback: CallbackQuery):
    async with async_session_maker() as session:
        _user, row = await load(callback, session)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        transaction_id = row[0].id
        text = card_text(*row)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"tx:delok:{transaction_id}")
    builder.button(text="Отмена", callback_data=f"tx:open:{transaction_id}")
    await callback.message.edit_text(
        f"Удалить эту операцию?\n{text}", reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tx:delok:"))
async def delete(callback: CallbackQuery):
    async with async_session_maker() as session:
        _user, row = await load(callback, session)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        transaction, _category, account = row
        text = card_text(*row)
        try:
            # счёт берём из найденной операции: он точно принадлежит пользователю
            await delete_transaction_by_id(session, transaction.id, account.id)
        except exc.InsufficientFunds:
            await callback.answer(CANT_DELETE_INCOME_TEXT, show_alert=True)
            return
        await session.commit()
    await callback.message.edit_text(f"🗑 Удалено\n{text}")
    await callback.answer()
