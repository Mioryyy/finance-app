import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import AccountStates
from app.bot.texts import ACCOUNT_NAME_PROMPT
from app.constants import ACCOUNT_TYPES_EMOJI, CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.repositories.account_repository import get_accounts_for_user, get_user_account
from app.repositories.user_repository import get_or_create_user, set_active_account

router = Router()


def totals_line(accounts):
    # валюты не складываем: сумма отдельно по каждой. Нужна, только если счетов
    # больше одного, иначе она повторяет единственную строку
    if len(accounts) < 2:
        return None
    totals = {}
    for account in accounts:
        totals[account.currency] = totals.get(account.currency, 0) + account.balance
    parts = [
        f"{amount} {CURRENCY_SYMBOLS[currency]}"
        for currency, amount in sorted(totals.items())
    ]
    return "💰 Всего: " + " · ".join(parts)


async def build_accounts_page(telegram_id):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        accounts = await get_accounts_for_user(session, user.id)
        text_list = ["Вот твои счета"]
        for account in accounts:
            if account.id == user.active_account_id:
                parts = ["✅"]
            else:
                parts = []
            parts.extend(
                [
                    ACCOUNT_TYPES_EMOJI[account.type],
                    html.escape(account.name),
                    "—",
                    str(account.balance),
                    CURRENCY_SYMBOLS[account.currency],
                ]
            )
            text = " ".join(p for p in parts if p)
            text_list.append(text)
        total = totals_line(accounts)
        if total:
            text_list.append(f"\n{total}")
        builder = InlineKeyboardBuilder()
        for account in accounts:
            if account.id != user.active_account_id:
                builder.button(
                    text=f"{account.name}", callback_data=f"acc:{account.id}"
                )
        builder.button(text="➕ Новый счёт", callback_data="account_new")
        builder.adjust(1)
        keyboard = builder.as_markup()
        if len(accounts) > 1:
            text = "\nХотите поменять счет?"
            text_list.append(text)
        text = "\n".join(text_list)
        return text, keyboard


async def start_account_creation(send_func, state):
    await state.clear()
    await send_func(f"Создаём новый счёт.\n{ACCOUNT_NAME_PROMPT}")
    await state.set_state(AccountStates.waiting_for_name)


@router.message(Command("accounts"))
async def show_accounts(message: Message):
    text, keyboard = await build_accounts_page(message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("create_account"))
async def cmd_create_account(message: Message, state: FSMContext):
    await start_account_creation(message.answer, state)


@router.callback_query(F.data == "account_new")
async def callback_create_account(callback: CallbackQuery, state: FSMContext):
    await start_account_creation(callback.message.answer, state)
    await callback.answer()


@router.callback_query(F.data.startswith("acc:"))
async def switch_account(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        account = await get_user_account(session, account_id, user.id)
        if account is None:
            await callback.answer("Счёт не найден", show_alert=True)
            return
        await set_active_account(session, user, account_id)
        await session.commit()
    text, keyboard = await build_accounts_page(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()
