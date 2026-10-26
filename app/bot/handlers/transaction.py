import html
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import TransactionStates
from app.bot.texts import account_label
from app.constants import CURRENCY_SYMBOLS, TX_TYPES
from app.database import async_session_maker
from app.parsing import parse_entry
from app.repositories.account_repository import get_account, get_user_account
from app.repositories.category_repository import get_user_category, show_category
from app.repositories.transaction_repository import (
    create_transaction,
    delete_transaction_by_id,
)
from app.repositories.user_repository import get_or_create_user

router = Router()


def format_date(tr_date):
    today = date.today()  # noqa: DTZ011
    if tr_date == today:
        return "сегодня"
    if tr_date == today - timedelta(days=1):
        return "вчера"
    return tr_date.strftime("%d.%m.%Y")


def entry_summary(data):
    kind = "💸 Расход" if data["tx_type"] == "expense" else "💰 Доход"
    description = html.escape(data["description"]) or "без описания"
    return (
        f"{kind}: <b>{description}</b> {data['amount']} {data['currency_symbol']}\n"
        f"{data['account_label']} · {format_date(data['tr_date'])}\n\n"
        "Выбери категорию"
    )


async def ask_category(answer_func, state: FSMContext, user_id: int):
    data = await state.get_data()
    await show_category(
        answer_func, state, data["tx_type"], user_id, text=entry_summary(data)
    )


@router.message(StateFilter(None))
async def add_transaction(message: Message, state: FSMContext):
    if not message.text:
        return
    if message.text.startswith("/"):
        await message.answer("Не знаю такой команды 🤔\nСписок команд: /help")
        return
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, message.from_user.id)
        if user.active_account_id is None:
            await message.answer(
                "❌ У тебя ещё нет счёта. Набери /start, чтобы создать его."
            )
            return
        account = await get_account(session, user.active_account_id)
    entry = parse_entry(message.text)
    if entry is None:
        await message.answer(
            "❌ Не могу распознать сумму.\n\n"
            "Напиши в формате: <b>описание сумма</b>\n"
            "Расход: <i>кофе 5</i>\n"
            "Доход: <i>+500 зарплата</i>"
        )
        return
    description, amount, tx_type = entry
    await state.update_data(
        description=description,
        amount=amount,
        tx_type=tx_type,
        tr_date=date.today(),  # noqa: DTZ011
        account_id=account.id,
        account_label=account_label(account),
        currency_symbol=CURRENCY_SYMBOLS.get(account.currency, account.currency),
    )
    await ask_category(message.answer, state, message.from_user.id)


@router.callback_query(F.data == "date:pick", TransactionStates.waiting_for_category)
async def pick_date(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="Вчера", callback_data="date:yesterday")
    builder.button(text="Сегодня", callback_data="date:today")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2, 1)
    await callback.message.edit_text(
        "Выбери день или напиши дату в формате дд.мм.гггг",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(TransactionStates.waiting_for_date)
    await callback.answer()


@router.callback_query(
    F.data.in_({"date:today", "date:yesterday"}), TransactionStates.waiting_for_date
)
async def process_quick_date(callback: CallbackQuery, state: FSMContext):
    tr_date = date.today()  # noqa: DTZ011
    if callback.data == "date:yesterday":
        tr_date -= timedelta(days=1)
    await state.update_data(tr_date=tr_date)
    await ask_category(callback.message.edit_text, state, callback.from_user.id)
    await callback.answer()


@router.message(TransactionStates.waiting_for_date)
async def parse_date_manual(message: Message, state: FSMContext):
    text = message.text
    if not text:
        await message.answer("Напиши дату в формате дд.мм.гггг!")
        return
    try:
        tr_date = datetime.strptime(text, "%d.%m.%Y").date()  # noqa: DTZ007
    except ValueError:
        await message.answer("Напиши дату в формате дд.мм.гггг!")
        return
    if tr_date > date.today():  # noqa: DTZ011
        await message.answer("Эта дата ещё не наступила. Напиши другую.")
        return
    await state.update_data(tr_date=tr_date)
    await ask_category(message.answer, state, message.from_user.id)


@router.callback_query(
    F.data.startswith("category:"), TransactionStates.waiting_for_category
)
async def handle_category_callback(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    description = data["description"]
    amount = data["amount"]
    tx_type = data["tx_type"]
    tr_date = data["tr_date"]
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        account = await get_user_account(session, data["account_id"], user.id)
        category = await get_user_category(session, category_id, user.id, tx_type)
        if account is None or category is None:
            await callback.answer("Счёт или категория не найдены", show_alert=True)
            return
        transaction = await create_transaction(
            session,
            account.id,
            category_id,
            description,
            amount,
            tx_type,
            tr_date,
        )
        await session.refresh(account)
        # после commit объекты протухают (expire_on_commit), поэтому всё берём до него
        currency_symbol = data["currency_symbol"]
        text = (
            f"✅ Записано: <b>{html.escape(description) or 'без описания'}</b> "
            f"{TX_TYPES[tx_type]}{amount} {currency_symbol} → "
            f"{html.escape(category.name)}\n"
            f"{account_label(account)} · {format_date(tr_date)} · "
            f"баланс {account.balance} {currency_symbol}"
        )
        undo_data = f"undo:{transaction.id}:{account.id}"
        await session.commit()
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="↩️ Отменить", callback_data=undo_data)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("category:"))
async def handle_category_oldcallback(callback: CallbackQuery):
    await callback.answer("Кнопка устарела, отправь трату заново", show_alert=True)
    await callback.message.delete()


@router.callback_query(F.data.startswith("undo:"))
async def undo_transaction(callback: CallbackQuery):
    _, transaction_id, account_id = callback.data.split(":")
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        account = await get_user_account(session, int(account_id), user.id)
        deleted = account is not None and await delete_transaction_by_id(
            session, int(transaction_id), account.id
        )
        if not deleted:
            await callback.answer("Операция уже удалена", show_alert=True)
            await callback.message.edit_reply_markup(reply_markup=None)
            return
        await session.refresh(account)
        currency_symbol = CURRENCY_SYMBOLS.get(account.currency, account.currency)
        text = (
            f"↩️ Операция отменена\n"
            f"{account_label(account)} · баланс {account.balance} {currency_symbol}"
        )
        await session.commit()
    await callback.message.edit_text(text)
    await callback.answer()
