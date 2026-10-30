import html
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import exceptions as exc
from app.bot.entry import ask_category, date_keyboard, format_date, show_confirmation
from app.bot.states import TransactionStates
from app.bot.texts import (
    QUICK_REVIEW_HINT,
    account_label,
    negative_balance_warning,
    not_enough_money_text,
)
from app.constants import (
    CURRENCY_SYMBOLS,
    QUICK_MAX_WITHOUT_HISTORY,
    QUICK_UNUSUAL_FACTOR,
    QUICK_UNUSUAL_MIN,
    TX_TYPES,
)
from app.database import async_session_maker
from app.parsing import parse_entry
from app.repositories.account_repository import get_account, get_user_account
from app.repositories.category_repository import (
    get_categories_for_user,
    get_user_category,
    guess_category_from_history,
)
from app.repositories.transaction_repository import (
    average_amount,
    create_transaction,
)
from app.repositories.user_repository import get_or_create_user
from app.services.ai_categorizer import guess_category_with_ai, is_enabled

router = Router()


async def suggest_category(message, user_id, description, tx_type):
    # сначала история пользователя (бесплатно и точнее всего), потом ИИ.
    # возвращает (id, название, источник) или None
    async with async_session_maker() as session:
        guess = await guess_category_from_history(
            session, user_id, description, tx_type
        )
        if guess:
            return guess.id, guess.name, "history"
        if not is_enabled() or not description.strip():
            return None
        categories = await get_categories_for_user(session, user_id, tx_type)
        categories = [(c.id, c.name) for c in categories]
    # сессия уже закрыта: пока ждём ИИ, соединение с базой не держим
    await message.bot.send_chat_action(message.chat.id, "typing")
    category_id = await guess_category_with_ai(description, categories)
    if category_id is None:
        return None
    return category_id, dict(categories)[category_id], "ai"


async def other_category(user_id, tx_type):
    # общая или своя категория «… Другое» нужного типа; (id, название) или None
    async with async_session_maker() as session:
        categories = await get_categories_for_user(session, user_id, tx_type)
    for category in categories:
        if category.name.endswith("Другое"):
            return category.id, category.name
    return None


async def is_unusual_amount(user_id, category_id, amount):
    async with async_session_maker() as session:
        average = await average_amount(session, user_id, category_id)
    if average is None:
        return amount > QUICK_MAX_WITHOUT_HISTORY
    return amount > max(average * QUICK_UNUSUAL_FACTOR, QUICK_UNUSUAL_MIN)


async def save_quick(message: Message, state: FSMContext, needs_review: bool):
    # быстрый ввод: сразу записываем, вместо подтверждения кнопка «Изменить»
    data = await state.get_data()
    await state.clear()
    currency_symbol = data["currency_symbol"]
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, message.from_user.id)
        account = await get_user_account(session, data["account_id"], user.id)
        try:
            transaction = await create_transaction(
                session,
                account.id,
                data["category_id"],
                data["description"],
                data["amount"],
                data["tx_type"],
                data["tr_date"],
                needs_review=needs_review,
            )
        except exc.InsufficientFunds:
            await message.answer(not_enough_money_text(account, currency_symbol))
            return
        await session.refresh(account)
        # всё нужное читаем до commit: после него объекты протухают
        transaction_id = transaction.id
        text = (
            f"⚡ <b>{html.escape(data['description']) or 'без описания'}</b> "
            f"{TX_TYPES[data['tx_type']]}{data['amount']} {currency_symbol} → "
            f"{html.escape(data['category_name'])}\n"
            f"{account_label(account)} · баланс {account.balance} {currency_symbol}"
            f"{negative_balance_warning(account.balance)}"
            f"{QUICK_REVIEW_HINT if needs_review else ''}"
        )
        await session.commit()
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить", callback_data=f"tx:open:{transaction_id}")
    await message.answer(text, reply_markup=builder.as_markup())


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
        user_id = user.id
        quick_entry = user.quick_entry
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
    suggestion = await suggest_category(message, user_id, description, tx_type)
    category_id, category_name, guess_source = suggestion or (None, None, None)
    await state.update_data(
        description=description,
        amount=amount,
        tx_type=tx_type,
        tr_date=date.today(),  # noqa: DTZ011
        account_id=account.id,
        account_label=account_label(account),
        currency_symbol=CURRENCY_SYMBOLS.get(account.currency, account.currency),
        category_id=category_id,
        category_name=category_name,
        guess_source=guess_source,
    )
    if quick_entry:
        if suggestion is None:
            # не угадали: кладём в «Другое», вечером человек сам поправит
            fallback = await other_category(user_id, tx_type)
            if fallback:
                category_id, category_name = fallback
                await state.update_data(
                    category_id=category_id, category_name=category_name
                )
        if category_id is not None:
            if not await is_unusual_amount(user_id, category_id, amount):
                await save_quick(message, state, needs_review=guess_source != "history")
                return
            # похоже на опечатку («шаурма 1000»): обычное окно подтверждения
            await state.update_data(unusual_amount=True)
            await show_confirmation(message.answer, state)
            return
    if suggestion:
        # категория найдена (по истории или ИИ): сразу показываем окно подтверждения
        await show_confirmation(message.answer, state)
    else:
        await ask_category(message.answer, state, message.from_user.id)


@router.callback_query(
    F.data.startswith("category:"), TransactionStates.waiting_for_category
)
async def choose_category(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        # id из кнопки не доверяем: категория должна быть доступна пользователю
        category = await get_user_category(
            session, category_id, user.id, data["tx_type"]
        )
        if category is None:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        category_name = category.name
    await state.update_data(
        category_id=category_id, category_name=category_name, guess_source=None
    )
    await show_confirmation(callback.message.edit_text, state)
    await callback.answer()


@router.callback_query(F.data == "entry:confirm", TransactionStates.waiting_for_confirm)
async def confirm_entry(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()  # первым делом: повторное нажатие уже не найдёт состояние
    async with async_session_maker() as session:
        user, _is_new = await get_or_create_user(session, callback.from_user.id)
        account = await get_user_account(session, data["account_id"], user.id)
        category = await get_user_category(
            session, data["category_id"], user.id, data["tx_type"]
        )
        if account is None or category is None:
            await callback.message.edit_text(
                "❌ Счёт или категория не найдены. Отправь трату заново"
            )
            await callback.answer()
            return
        currency_symbol = data["currency_symbol"]
        try:
            await create_transaction(
                session,
                account.id,
                category.id,
                data["description"],
                data["amount"],
                data["tx_type"],
                data["tr_date"],
            )
        except exc.InsufficientFunds:
            await callback.message.edit_text(
                not_enough_money_text(account, currency_symbol)
            )
            await callback.answer()
            return
        await session.refresh(account)
        # после commit объекты протухают (expire_on_commit), поэтому текст собираем до него
        title = (
            "✅ Трата создана" if data["tx_type"] == "expense" else "✅ Доход создан"
        )
        text = (
            f"{title}\n"
            f"<b>{html.escape(data['description']) or 'без описания'}</b> "
            f"{TX_TYPES[data['tx_type']]}{data['amount']} {currency_symbol} → "
            f"{html.escape(category.name)}\n"
            f"{account_label(account)} · {format_date(data['tr_date'])} · "
            f"баланс {account.balance} {currency_symbol}"
            f"{negative_balance_warning(account.balance)}"
        )
        await session.commit()
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data == "entry:date", TransactionStates.waiting_for_confirm)
async def change_date(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Выбери день или напиши дату в формате дд.мм.гггг",
        reply_markup=date_keyboard(),
    )
    await state.set_state(TransactionStates.waiting_for_date)
    await callback.answer()


@router.callback_query(
    F.data.in_({"date:today", "date:yesterday"}), TransactionStates.waiting_for_date
)
async def choose_quick_date(callback: CallbackQuery, state: FSMContext):
    tr_date = date.today()  # noqa: DTZ011
    if callback.data == "date:yesterday":
        tr_date -= timedelta(days=1)
    await state.update_data(tr_date=tr_date)
    await show_confirmation(callback.message.edit_text, state)
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
    await show_confirmation(message.answer, state)


@router.callback_query(
    F.data == "entry:category", TransactionStates.waiting_for_confirm
)
async def change_category(callback: CallbackQuery, state: FSMContext):
    await ask_category(
        callback.message.edit_text, state, callback.from_user.id, with_back=True
    )
    await callback.answer()


@router.callback_query(
    F.data == "entry:back",
    StateFilter(
        TransactionStates.waiting_for_date, TransactionStates.waiting_for_category
    ),
)
async def back_to_confirmation(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("category_id") is None:
        await callback.answer("Сначала выбери категорию", show_alert=True)
        return
    await show_confirmation(callback.message.edit_text, state)
    await callback.answer()


@router.message(
    StateFilter(
        TransactionStates.waiting_for_category, TransactionStates.waiting_for_confirm
    )
)
async def hint_use_buttons(message: Message):
    await message.answer("Нажми одну из кнопок под записью или /cancel для отмены")


@router.callback_query(F.data.startswith("undo:"))
async def old_undo_callback(callback: CallbackQuery):
    # кнопки «Отменить» больше нет, но она могла остаться в старых сообщениях
    await callback.answer(
        "Эта кнопка устарела. Удалить операцию можно через /history",
        show_alert=True,
    )
    await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith(("category:", "entry:", "date:")))
async def old_callback(callback: CallbackQuery):
    await callback.answer("Кнопка устарела, отправь трату заново", show_alert=True)
    await callback.message.delete()
