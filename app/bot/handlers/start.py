import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.handlers.account_edit import account_edit_keyboard, account_summary
from app.bot.states import AccountStates
from app.bot.texts import (
    ACCOUNT_CREATED_HINT,
    FIRST_ENTRY_HINT,
    ONBOARDING_CURRENCY_TEXT,
    START_TEXT,
)
from app.constants import (
    ACCOUNT_TYPES,
    CURRENCY_SYMBOLS,
    ONBOARDING_CURRENCIES,
)
from app.database import async_session_maker
from app.repositories.account_repository import create_account
from app.repositories.user_repository import (
    create_first_account,
    get_or_create_user,
    set_active_account,
)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, message.from_user.id)
        # читаем до commit: после него объект протухает (expire_on_commit),
        # а вне сессии подгрузить значение заново уже нельзя
        has_account = user.active_account_id is not None
        await session.commit()
    if not has_account:
        # первый запуск: одно нажатие до первой траты. Название, тип и остаток
        # человек поправит потом кнопками, если захочет
        builder = InlineKeyboardBuilder()
        for currency in ONBOARDING_CURRENCIES:
            builder.button(text=currency, callback_data=f"onboard:{currency}")
        builder.adjust(4)
        await message.answer(
            f"{START_TEXT}{ONBOARDING_CURRENCY_TEXT}",
            reply_markup=builder.as_markup(),
        )
        return

    await message.answer(f"{START_TEXT}С возвращением! Напиши трату 👇")


@router.callback_query(F.data.startswith("onboard:"))
async def onboarding_currency(callback: CallbackQuery):
    currency = callback.data.split(":", 1)[1]
    if currency not in ONBOARDING_CURRENCIES:
        await callback.answer("Кнопка устарела, набери /start", show_alert=True)
        return
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        account = await create_first_account(session, user, currency)
        if account is None:
            await callback.answer("Счёт уже создан, напиши трату", show_alert=True)
            await callback.message.edit_reply_markup(reply_markup=None)
            return
        text = (
            f"✅ Готово! Создал счёт\n{account_summary(account)}\n\n{FIRST_ENTRY_HINT}"
        )
        keyboard = account_edit_keyboard(account.id)
        await session.commit()
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.message(AccountStates.waiting_for_name)
async def process_account_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь название счёта текстом")
        return
    await state.update_data(account_name=message.text)
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Карта", callback_data="acctype:card")
    builder.button(text="💵 Наличные", callback_data="acctype:cash")
    builder.button(text="🪙 Криптовалюта", callback_data="acctype:crypto")
    keyboard = builder.as_markup()
    await message.answer("Какой тип будет у счёта?", reply_markup=keyboard)
    await state.set_state(AccountStates.waiting_for_type)


@router.callback_query(F.data.startswith("acctype:"), AccountStates.waiting_for_type)
async def process_account_type(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    account_type = callback.data.split(":")[1]
    await state.update_data(type=account_type)
    builder = InlineKeyboardBuilder()
    for key in CURRENCY_SYMBOLS:
        builder.button(text=key, callback_data=f"curr:{key}")
    builder.adjust(2)
    keyboard = builder.as_markup()
    await callback.message.answer("Какая валюта будет у счёта?", reply_markup=keyboard)
    await callback.answer()
    await state.set_state(AccountStates.waiting_for_currency)


@router.callback_query(F.data.startswith("curr:"), AccountStates.waiting_for_currency)
async def process_account_currency(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    currency = callback.data.split(":")[1]
    await state.update_data(currency=currency)
    data = await state.get_data()
    name = data["account_name"]
    account_type = data["type"]
    acctype = ACCOUNT_TYPES[account_type]
    currency = data["currency"]
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        account = await create_account(session, user.id, name, account_type, currency)
        await set_active_account(session, user, account.id)
        await session.commit()
    await callback.message.answer(
        f"✅ Создан счёт {acctype} <b>{html.escape(name)}</b> в валюте {currency}\n\n"
        f"{ACCOUNT_CREATED_HINT}"
    )
    await state.clear()
