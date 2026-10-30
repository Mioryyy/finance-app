"""Стенд для тестов диалогов: поддельный Telegram и «пользователь», который пишет боту."""

import asyncio
import itertools
from datetime import date

from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

TG_ID = 777


class FakeSession(BaseSession):
    """Вместо запросов в Telegram запоминает, что бот попытался отправить."""

    def __init__(self):
        super().__init__()
        self.sent = []  # (вид, текст, клавиатура) каждого ответа бота
        self.other = []  # остальные запросы к Telegram, например «печатает…»
        self.chats = []  # chat_id каждого сообщения из sent (тот же порядок)
        self.fail_for = set()  # в эти chat_id отправка «не удаётся»
        self.blocked = set()  # эти chat_id «заблокировали бота»
        self.counter = itertools.count(1000)

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError

    async def make_request(self, bot, method, timeout=None):
        # настоящий запрос в Telegram занимает время, и в этот момент выполняются
        # другие обработчики. Уступаем управление, чтобы тесты могли поймать гонки
        await asyncio.sleep(0)
        chat_id = getattr(method, "chat_id", None)
        if chat_id in self.blocked:
            raise TelegramForbiddenError(
                method=method, message="Forbidden: bot was blocked by the user"
            )
        if chat_id in self.fail_for:
            raise TelegramBadRequest(
                method=method, message="Bad Request: chat not found"
            )
        if isinstance(method, SendMessage | EditMessageText):
            keyboard = getattr(method, "reply_markup", None)
            self.sent.append((type(method).__name__, method.text, keyboard))
            self.chats.append(chat_id)
            return Message(
                message_id=next(self.counter),
                date=date.today(),
                chat=Chat(id=TG_ID, type="private"),
                text=method.text,
            )
        self.other.append(type(method).__name__)
        return True


class Client:
    """Пользователь, который пишет боту и нажимает кнопки."""

    def __init__(self, dp, bot, fake, telegram_id=TG_ID):
        self.dp, self.bot, self.fake = dp, bot, fake
        self.update_id = itertools.count(1)
        self.user = User(id=telegram_id, is_bot=False, first_name="Тест")
        self.chat = Chat(id=telegram_id, type="private")

    async def say(self, text):
        message = Message(
            message_id=next(self.fake.counter),
            date=date.today(),
            chat=self.chat,
            from_user=self.user,
            text=text,
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=next(self.update_id), message=message)
        )

    async def press(self, data):
        # кнопку нажимают в последнем сообщении бота
        message = Message(
            message_id=next(self.fake.counter),
            date=date.today(),
            chat=self.chat,
            text="…",
        )
        callback = CallbackQuery(
            id=str(next(self.update_id)),
            from_user=self.user,
            chat_instance="x",
            message=message,
            data=data,
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=next(self.update_id), callback_query=callback)
        )

    @property
    def last(self):
        kind, text, keyboard = self.fake.sent[-1]
        buttons = []
        if keyboard:
            buttons = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        return text, buttons
