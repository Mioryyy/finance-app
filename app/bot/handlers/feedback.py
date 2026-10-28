import html
import logging
import math
import os
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.states import FeedbackStates
from app.bot.texts import FEEDBACK_CHOICE_TEXT, FEEDBACK_PROMPT, FEEDBACK_THANKS
from app.constants import FEEDBACK_COOLDOWN_SECONDS, FEEDBACK_MAX_LENGTH

logger = logging.getLogger(__name__)
router = Router()

# когда пользователь в последний раз отправил отзыв: защита от спама.
# хранится в памяти, после перезапуска бота обнуляется, для этой цели достаточно
last_sent: dict[int, float] = {}


def now() -> float:
    # отдельная функция, чтобы тесты могли «перемотать» время
    return time.monotonic()


def admin_chat_id() -> int | None:
    # читаем при каждом вызове, а не при импорте: так значение подхватывается
    # после load_dotenv() и его можно менять в тестах
    try:
        return int(os.getenv("ADMIN_CHAT_ID", "").strip())
    except ValueError:
        return None


def seconds_left(telegram_id: int) -> int:
    sent_at = last_sent.get(telegram_id)
    if sent_at is None:
        return 0
    return max(0, math.ceil(FEEDBACK_COOLDOWN_SECONDS - (now() - sent_at)))


def feedback_for_admin(text: str, user, anonymous: bool) -> str:
    # всё, что пишет пользователь (и его имя), экранируем: бот шлёт HTML
    if anonymous:
        sender = "анонимно"
    else:
        handle = f" @{html.escape(user.username)}" if user.username else ""
        sender = (
            f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
            f"{handle} · id {user.id}"
        )
    return f"💬 <b>Новый отзыв</b>\nОт: {sender}\n\n{html.escape(text)}"


@router.message(Command("feedback"), StateFilter("*"))
async def cmd_feedback(message: Message, state: FSMContext):
    await state.clear()
    if admin_chat_id() is None:
        # ADMIN_CHAT_ID не задан: некуда пересылать, поэтому отзыв не собираем
        await message.answer("Приём отзывов сейчас выключен.")
        return
    wait = seconds_left(message.from_user.id)
    if wait:
        await message.answer(
            f"Ты только что отправил отзыв. Подожди {wait} с и напиши снова."
        )
        return
    await message.answer(FEEDBACK_PROMPT)
    await state.set_state(FeedbackStates.waiting_for_text)


@router.message(FeedbackStates.waiting_for_text)
async def receive_feedback_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Отправь отзыв текстом или /cancel, чтобы отменить.")
        return
    if len(text) > FEEDBACK_MAX_LENGTH:
        await message.answer(
            f"Слишком длинно: {len(text)} из {FEEDBACK_MAX_LENGTH} символов. "
            "Сократи и отправь снова."
        )
        return
    await state.update_data(feedback_text=text)
    builder = InlineKeyboardBuilder()
    builder.button(text="✉️ С моим именем", callback_data="feedback:named")
    builder.button(text="🕶 Анонимно", callback_data="feedback:anonymous")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2, 1)
    await message.answer(FEEDBACK_CHOICE_TEXT, reply_markup=builder.as_markup())
    await state.set_state(FeedbackStates.waiting_for_choice)


@router.message(FeedbackStates.waiting_for_choice)
async def hint_use_buttons(message: Message):
    await message.answer("Выбери кнопкой под сообщением или нажми /cancel.")


@router.callback_query(
    F.data.in_({"feedback:named", "feedback:anonymous"}),
    FeedbackStates.waiting_for_choice,
)
async def send_feedback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()  # первым делом: повторное нажатие не отправит отзыв второй раз
    user = callback.from_user
    text = data.get("feedback_text")
    admin = admin_chat_id()
    if not text or admin is None:
        await callback.message.edit_text(
            "Не получилось отправить. Начни заново: /feedback"
        )
        await callback.answer()
        return
    wait = seconds_left(user.id)
    if wait:
        await callback.message.edit_text(
            f"Ты только что отправил отзыв. Подожди {wait} с и напиши снова."
        )
        await callback.answer()
        return
    anonymous = callback.data == "feedback:anonymous"
    # бронируем лимит ДО отправки: между проверкой выше и этой записью нет await,
    # поэтому второй одновременный клик уже увидит бронь и ничего не отправит
    last_sent[user.id] = now()
    try:
        await bot.send_message(admin, feedback_for_admin(text, user, anonymous))
    except TelegramAPIError:
        # например, неверный ADMIN_CHAT_ID или автор заблокировал бота.
        # текст отзыва в лог не пишем: он может быть личным
        logger.exception("Could not deliver feedback to ADMIN_CHAT_ID")
        last_sent.pop(user.id, None)  # не дошло: можно сразу попробовать снова
        await callback.message.edit_text(
            "Не получилось отправить отзыв. Попробуй позже."
        )
        await callback.answer()
        return
    await callback.message.edit_text(FEEDBACK_THANKS)
    await callback.answer()


@router.callback_query(F.data.startswith("feedback:"))
async def old_feedback_callback(callback: CallbackQuery):
    # кнопка из старого сообщения (состояния уже нет): ничего не отправляем
    await callback.answer("Кнопка устарела. Набери /feedback заново", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)
