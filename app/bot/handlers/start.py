from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import AccountStates
from app.constants import ACCOUNT_TYPES, CURRENCY_SYMBOLS
from app.database import async_session_maker
from app.repositories.account_repository import create_account
from app.repositories.user_repository import get_or_create_user, set_active_account

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, message.from_user.id)
        await session.commit()
    if user.active_account_id is None:

        await message.answer(
            """👋 Привет! Я помогу тебе следить за расходами.

💸 Чтобы добавить трату, просто напиши описание и сумму:
кофе 50

🏷 Есть готовые категории, а если чего-то не хватает — можно создать свою через /add_category

Для начала создадим твой первый счет👇""",
        )
        await message.answer("Как его назовём?")
        await state.set_state(AccountStates.waiting_for_name)
        return

    await message.answer("""👋 Привет! Я помогу тебе следить за расходами.

💸 Чтобы добавить трату, просто напиши описание и сумму:
кофе 50

🏷 Есть готовые категории, а если чего-то не хватает — можно создать свою через /add_category

Погнали! Напиши свою первую трату 👇""")


@router.message(AccountStates.waiting_for_name)
async def process_account_name(message: Message, state: FSMContext):
    await state.update_data(account_name=message.text)
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Карта", callback_data="acctype:card")
    builder.button(text="💵 Наличные", callback_data="acctype:cash")
    builder.button(text="🪙 Криптовалюта", callback_data="acctype:crypto")
    keyboard = builder.as_markup()
    await message.answer("Какой тип будет у счета?", reply_markup=keyboard)
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
    await callback.message.answer("Какая валюта будет у счета?", reply_markup=keyboard)
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
        f"Вы создали свой первый счет:\n{acctype} {name} в валюте {currency}"
    )
    await state.clear()
