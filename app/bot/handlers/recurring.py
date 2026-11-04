"""Регулярные операции (зарплата, подписки): /recurring.

Порядок диалога: тип -> категория -> название и сумма -> период
(месяц, каждые N дней, год) -> дата. Вопросы «Добавить?» приходят из
app/services/recurring.py, а кнопки под ними обрабатываются здесь.
Из списка подписку можно открыть и поправить сумму или ближайший платёж.
"""

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import exceptions as exc
from app.bot.states import RecurringEditStates, RecurringStates
from app.bot.texts import account_label
from app.constants import (
    CURRENCY_SYMBOLS,
    RECURRING_MAX_INTERVAL_DAYS,
    RECURRING_MAX_PER_USER,
)
from app.database import async_session_maker
from app.parsing import (
    parse_amount,
    parse_day_month,
    parse_entry,
    parse_upcoming_date,
)
from app.repositories.account_repository import get_user_account
from app.repositories.category_repository import (
    get_categories_for_user,
    get_user_category,
)
from app.repositories.recurring_repository import (
    count_user_recurring,
    create_recurring,
    delete_recurring,
    get_recurring_for_update,
    get_user_payment,
    get_user_recurring,
    set_recurring_amount,
    set_recurring_next_due,
)
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user
from app.services.limits import limit_warning
from app.services.recurring import (
    advance_due,
    first_due,
    parse_due_token,
    payment_label,
    period_text,
    today_minsk,
    year_due,
)

router = Router()

INTRO = (
    "🔁 <b>Регулярные операции</b>\n"
    "Зарплата, стипендия, подписки: в день платежа вечером я спрошу, "
    "добавить ли операцию. Сам ничего не запишу, пока ты не нажмёшь «Добавить».\n\n"
)
NO_ACCOUNT = "❌ У тебя ещё нет счёта. Набери /start, чтобы создать его."
ALREADY_DONE = "Это уже обработано"
NOT_FOUND = "Подписка не найдена: возможно, её уже удалили"
DATE_HINT = "Напиши <i>сегодня</i>, <i>завтра</i> или дату <i>дд.мм</i>"


async def build_recurring_page(telegram_id):
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, telegram_id)
        rows = await get_user_recurring(session, user.id)
        await session.commit()
    lines = []
    builder = InlineKeyboardBuilder()
    for payment, category_name, currency in rows:
        lines.append(
            f"• {payment_label(payment, category_name, currency)}\n"
            f"   {period_text(payment)} · ближайший {payment.next_due.strftime('%d.%m.%Y')}"
        )
        short = payment.description or category_name
        builder.button(text=f"✏️ {short[:20]}", callback_data=f"rec:open:{payment.id}")
    builder.button(text="➕ Добавить", callback_data="rec:new")
    builder.adjust(1)
    body = "\n".join(lines) if lines else "Пока ничего нет."
    return INTRO + body, builder.as_markup()


def card_keyboard(payment_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Сумма", callback_data=f"rec:amt:{payment_id}")
    builder.button(text="📅 Ближайший платёж", callback_data=f"rec:next:{payment_id}")
    builder.button(text="🗑 Удалить", callback_data=f"rec:del:{payment_id}")
    builder.button(text="⬅️ К списку", callback_data="rec:list")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def card_text(payment, category_name, currency):
    return (
        f"{payment_label(payment, category_name, currency)}\n"
        f"{period_text(payment)}\n"
        f"Ближайший платёж: {payment.next_due.strftime('%d.%m.%Y')}"
    )


@router.message(Command("recurring"), StateFilter("*"))
async def cmd_recurring(message: Message, state: FSMContext):
    await state.clear()
    text, keyboard = await build_recurring_page(message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "rec:list")
async def back_to_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text, keyboard = await build_recurring_page(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# ---------- создание ----------


@router.callback_query(F.data == "rec:new")
async def choose_type(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        if user.active_account_id is None:
            await callback.answer(NO_ACCOUNT, show_alert=True)
            return
        if await count_user_recurring(session, user.id) >= RECURRING_MAX_PER_USER:
            await callback.answer(
                f"Можно не больше {RECURRING_MAX_PER_USER} регулярных операций",
                show_alert=True,
            )
            return
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Подписка (расход)", callback_data="rec:type:expense")
    builder.button(text="💰 Зарплата (доход)", callback_data="rec:type:income")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    await state.set_state(RecurringStates.waiting_for_type)
    await callback.message.answer("Что добавляем?", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(
    F.data.in_({"rec:type:expense", "rec:type:income"}),
    RecurringStates.waiting_for_type,
)
async def choose_category(callback: CallbackQuery, state: FSMContext):
    tx_type = callback.data.split(":")[2]
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        categories = await get_categories_for_user(session, user.id, tx_type)
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(text=category.name, callback_data=f"rec:cat:{category.id}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    await state.update_data(tx_type=tx_type)
    await state.set_state(RecurringStates.waiting_for_category)
    await callback.message.edit_text(
        "Выбери категорию", reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(
    F.data.regexp(r"^rec:cat:\d+$"), RecurringStates.waiting_for_category
)
async def ask_amount(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        # id из кнопки не доверяем: категория должна быть доступна пользователю
        category = await get_user_category(
            session, category_id, user.id, data["tx_type"]
        )
        if category is None:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        category_name = category.name
    await state.update_data(category_id=category_id)
    await state.set_state(RecurringStates.waiting_for_amount)
    await callback.message.edit_text(
        f"Категория: {category_name}\n\n"
        "Напиши название и сумму, например: <i>Spotify 5</i> или "
        "<i>стипендия 120</i>\nПередумал: /cancel"
    )
    await callback.answer()


@router.message(RecurringStates.waiting_for_amount)
async def ask_period(message: Message, state: FSMContext):
    entry = parse_entry(message.text)
    if entry is None:
        await message.answer(
            "Не понял. Напиши название и сумму, например: <i>Spotify 5</i>"
        )
        return
    description, amount, _sign = entry  # знак плюса не важен: тип уже выбран
    await state.update_data(description=description[:100], amount=amount)
    await state.set_state(RecurringStates.waiting_for_period)
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Каждый месяц", callback_data="rec:per:month")
    builder.button(text="🔁 Каждые N дней", callback_data="rec:per:days")
    builder.button(text="🎂 Раз в год", callback_data="rec:per:year")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    await message.answer(
        "Как часто? Если сервис списывает «раз в 30 дней», а не 15-го числа, "
        "выбери «Каждые N дней»: месяцы разной длины, и дата будет уезжать.",
        reply_markup=builder.as_markup(),
    )


PERIOD_PROMPTS = {
    "month": (
        RecurringStates.waiting_for_day,
        "Какого числа каждый месяц? Напиши число от 1 до 31.\n"
        "Если в месяце нет такого дня, спрошу в его последний день.",
    ),
    "days": (
        RecurringStates.waiting_for_interval,
        "Через сколько дней платёж повторяется? Напиши число от 1 до "
        f"{RECURRING_MAX_INTERVAL_DAYS}: <i>30</i> для «раз в 30 дней», "
        "<i>7</i> для раза в неделю.",
    ),
    "year": (
        RecurringStates.waiting_for_year_date,
        "Какого числа и месяца раз в год? Напиши <i>дд.мм</i>, например <i>05.11</i>.",
    ),
}


@router.callback_query(
    F.data.in_({"rec:per:month", "rec:per:days", "rec:per:year"}),
    RecurringStates.waiting_for_period,
)
async def choose_period(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[2]
    new_state, prompt = PERIOD_PROMPTS[period]
    await state.update_data(period=period)
    await state.set_state(new_state)
    await callback.message.edit_text(prompt)
    await callback.answer()


async def finish_creation(
    message: Message,
    state: FSMContext,
    *,
    first,
    day_of_month,
    period,
    interval_days=None,
    anchor_month=None,
):
    # общий конец диалога для всех периодов: создаём платёж и подтверждаем
    data = await state.get_data()
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        if user.active_account_id is None:
            await state.clear()
            await message.answer(NO_ACCOUNT)
            return
        category = await get_user_category(
            session, data["category_id"], user.id, data["tx_type"]
        )
        account = await get_user_account(session, user.active_account_id, user.id)
        if category is None or account is None:
            await state.clear()
            await message.answer(
                "Категория или счёт не найдены. Начни заново: /recurring"
            )
            return
        payment = await create_recurring(
            session,
            user.id,
            account.id,
            category.id,
            data["tx_type"],
            data["description"],
            data["amount"],
            day_of_month,
            first,
            period=period,
            interval_days=interval_days,
            anchor_month=anchor_month,
        )
        # текст собираем до commit: после него объекты устаревают
        confirmation = (
            f"✅ Готово: {payment_label(payment, category.name, account.currency)}\n"
            f"{account_label(account)} · {period_text(payment)}\n"
            f"Ближайший платёж: {payment.next_due.strftime('%d.%m.%Y')}"
        )
        await session.commit()
    await state.clear()
    await message.answer(confirmation)


@router.message(RecurringStates.waiting_for_day)
async def save_monthly(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or not 1 <= int(text) <= 31:
        await message.answer("Напиши число месяца от 1 до 31")
        return
    day = int(text)
    await finish_creation(
        message,
        state,
        first=first_due(day, today_minsk()),
        day_of_month=day,
        period="month",
    )


@router.message(RecurringStates.waiting_for_year_date)
async def save_yearly(message: Message, state: FSMContext):
    parsed = parse_day_month(message.text or "")
    if parsed is None:
        await message.answer("Не понял. Напиши день и месяц: <i>05.11</i>")
        return
    day, month = parsed
    await finish_creation(
        message,
        state,
        first=year_due(day, month, today_minsk()),
        day_of_month=day,
        period="year",
        anchor_month=month,
    )


@router.message(RecurringStates.waiting_for_interval)
async def ask_start(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or not 1 <= int(text) <= RECURRING_MAX_INTERVAL_DAYS:
        await message.answer(f"Напиши число дней от 1 до {RECURRING_MAX_INTERVAL_DAYS}")
        return
    await state.update_data(interval_days=int(text))
    await state.set_state(RecurringStates.waiting_for_start)
    await message.answer(f"Когда ближайший платёж? {DATE_HINT}")


@router.message(RecurringStates.waiting_for_start)
async def save_every_n_days(message: Message, state: FSMContext):
    today = today_minsk()
    first = parse_upcoming_date(message.text or "", today)
    if first is None or first < today:
        await message.answer(f"Не понял или дата уже прошла. {DATE_HINT}")
        return
    data = await state.get_data()
    await finish_creation(
        message,
        state,
        first=first,
        day_of_month=first.day,
        period="days",
        interval_days=data["interval_days"],
    )


# ---------- карточка подписки: правка и удаление ----------


async def load_card(session, telegram_id, payment_id):
    user, _ = await get_or_create_user(session, telegram_id)
    return user, await get_user_payment(session, payment_id, user.id)


@router.callback_query(F.data.regexp(r"^rec:open:\d+$"))
async def open_card(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    payment_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        _user, row = await load_card(session, callback.from_user.id, payment_id)
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        text = card_text(*row)
    await callback.message.edit_text(text, reply_markup=card_keyboard(payment_id))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^rec:(amt|next):\d+$"))
async def start_edit(callback: CallbackQuery, state: FSMContext):
    field, raw_id = callback.data.split(":")[1:]
    async with async_session_maker() as session:
        _user, row = await load_card(session, callback.from_user.id, int(raw_id))
        if row is None:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
    await state.clear()
    await state.update_data(payment_id=int(raw_id))
    if field == "amt":
        await state.set_state(RecurringEditStates.waiting_for_amount)
        await callback.message.answer(
            "Напиши новую сумму, например: <i>6,5</i>\n"
            "Она применится к следующим платежам, уже записанные не изменятся.\n"
            "Передумал: /cancel"
        )
    else:
        await state.set_state(RecurringEditStates.waiting_for_date)
        await callback.message.answer(
            f"Когда ближайший платёж? {DATE_HINT}\nПередумал: /cancel"
        )
    await callback.answer()


async def save_edit(message: Message, state: FSMContext, apply, title):
    # apply(session, payment) меняет платёж; commit только после него
    data = await state.get_data()
    async with async_session_maker() as session:
        _user, row = await load_card(session, message.from_user.id, data["payment_id"])
        if row is None:
            await state.clear()
            await message.answer(NOT_FOUND)
            return
        payment, category_name, currency = row
        await apply(session, payment)
        text = card_text(payment, category_name, currency)
        payment_id = payment.id
        await session.commit()
    await state.clear()
    await message.answer(f"{title}\n{text}", reply_markup=card_keyboard(payment_id))


@router.message(RecurringEditStates.waiting_for_amount)
async def save_new_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer("Напиши сумму числом, например: <i>6,5</i>")
        return

    async def apply(session, payment):
        await set_recurring_amount(session, payment, amount)

    await save_edit(message, state, apply, "✅ Сумма изменена")


@router.message(RecurringEditStates.waiting_for_date)
async def save_new_date(message: Message, state: FSMContext):
    today = today_minsk()
    new_date = parse_upcoming_date(message.text or "", today)
    if new_date is None or new_date < today:
        await message.answer(f"Не понял или дата уже прошла. {DATE_HINT}")
        return

    async def apply(session, payment):
        await set_recurring_next_due(session, payment, new_date)

    await save_edit(message, state, apply, "✅ Дата изменена")


@router.callback_query(F.data.regexp(r"^rec:del:\d+$"))
async def remove(callback: CallbackQuery):
    payment_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        deleted = await delete_recurring(session, payment_id, user.id)
        await session.commit()
    if not deleted:
        await callback.answer("Уже удалено", show_alert=True)
        return
    text, keyboard = await build_recurring_page(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer("Удалено")


# ---------- ответ на вечерний вопрос «Добавить?» ----------


@router.callback_query(F.data.regexp(r"^rec:(ok|skip):\d+:\d{8}$"))
async def answer_prompt(callback: CallbackQuery):
    _, action, raw_id, raw_due = callback.data.split(":")
    due = parse_due_token(raw_due)
    async with async_session_maker() as session:
        user, _ = await get_or_create_user(session, callback.from_user.id)
        payment = await get_recurring_for_update(session, int(raw_id), user.id)
        # дата из кнопки должна совпасть с текущей: после первого нажатия
        # next_due уже сдвинут, и второе нажатие (или старое сообщение) попадёт сюда
        if payment is None or due is None or payment.next_due != due:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.answer(ALREADY_DONE, show_alert=True)
            return
        category = await get_user_category(
            session, payment.category_id, user.id, payment.tx_type
        )
        account = await get_user_account(session, payment.account_id, user.id)
        if category is None or account is None:
            await callback.answer("Счёт или категория не найдены", show_alert=True)
            return
        label = payment_label(payment, category.name, account.currency)
        if action == "skip":
            payment.next_due = advance_due(payment, due)
            await session.commit()
            await callback.message.edit_text(f"⏭ Пропущено\n{label}")
            await callback.answer()
            return
        try:
            await create_transaction(
                session,
                account.id,
                category.id,
                payment.description,
                payment.amount,
                payment.tx_type,
                due,
            )
        except exc.InsufficientFunds:
            # кнопки остаются: можно пополнить счёт и нажать ещё раз
            await callback.answer(
                "Не хватает денег на счёте. Пополни его и нажми ещё раз",
                show_alert=True,
            )
            return
        await session.refresh(account)
        text = (
            f"✅ Добавлено\n{label}\n"
            f"{account_label(account)} · баланс {account.balance} "
            f"{CURRENCY_SYMBOLS.get(account.currency, account.currency)}"
        )
        if payment.tx_type == "expense":
            warning = await limit_warning(
                session,
                user.id,
                category.id,
                category.name,
                account.currency,
                due,
                payment.amount,
            )
            if warning:
                text += f"\n\n{warning}"
        payment.next_due = advance_due(payment, due)
        await session.commit()
    await callback.message.edit_text(text)
    await callback.answer()
