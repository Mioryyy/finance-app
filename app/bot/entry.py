import html
from datetime import date, timedelta

from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import TransactionStates
from app.bot.texts import UNUSUAL_AMOUNT_HINT
from app.repositories.category_repository import show_category


def format_date(tr_date):
    today = date.today()  # noqa: DTZ011
    if tr_date == today:
        return "сегодня"
    if tr_date == today - timedelta(days=1):
        return "вчера"
    return tr_date.strftime("%d.%m.%Y")


def entry_head(data):
    kind = "💸 Расход" if data["tx_type"] == "expense" else "💰 Доход"
    description = html.escape(data["description"]) or "без описания"
    return f"{kind}: <b>{description}</b> {data['amount']} {data['currency_symbol']}"


def category_prompt(data):
    return (
        f"{entry_head(data)}\n"
        f"{data['account_label']} · {format_date(data['tr_date'])}\n\n"
        "Выбери категорию"
    )


GUESS_HINTS = {
    "history": "\n💡 Категория угадана по твоей истории",
    "ai": "\n🤖 Категорию предложил ИИ, проверь её",
}


def confirmation_text(data):
    hint = GUESS_HINTS.get(data.get("guess_source"), "")
    if data.get("unusual_amount"):
        hint += UNUSUAL_AMOUNT_HINT
    return (
        f"{entry_head(data)}\n"
        f"🏷 {html.escape(data['category_name'])}\n"
        f"{data['account_label']} · {format_date(data['tr_date'])}{hint}\n\n"
        "Всё верно?"
    )


def confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="entry:confirm")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.button(text="📅 Сменить дату", callback_data="entry:date")
    builder.button(text="🏷 Сменить категорию", callback_data="entry:category")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def date_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Вчера", callback_data="date:yesterday")
    builder.button(text="Сегодня", callback_data="date:today")
    builder.button(text="⬅️ Назад", callback_data="entry:back")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2, 2)
    return builder.as_markup()


async def show_confirmation(send_func, state: FSMContext):
    # send_func — message.answer (новое сообщение) или callback.message.edit_text
    # (то же сообщение): оба принимают text= и reply_markup=
    data = await state.get_data()
    await send_func(text=confirmation_text(data), reply_markup=confirm_keyboard())
    await state.set_state(TransactionStates.waiting_for_confirm)


async def ask_category(send_func, state: FSMContext, user_id: int, with_back=False):
    data = await state.get_data()
    await show_category(
        send_func,
        state,
        data["tx_type"],
        user_id,
        text=category_prompt(data),
        with_back=with_back,
    )
