"""Диалог записи траты целиком: настоящие хендлеры, подменённый Telegram и БД finance_test."""

import itertools
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import func, select

from app.bot.handlers import add_category, cancel, transaction
from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories import category_repository
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user, set_active_account

TG_ID = 777


class FakeSession(BaseSession):
    """Вместо запросов в Telegram запоминает, что бот попытался отправить."""

    def __init__(self):
        super().__init__()
        self.sent = []  # (вид, текст, клавиатура) каждого ответа бота
        self.counter = itertools.count(1000)

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage | EditMessageText):
            keyboard = getattr(method, "reply_markup", None)
            self.sent.append((type(method).__name__, method.text, keyboard))
            return Message(
                message_id=next(self.counter),
                date=date.today(),
                chat=Chat(id=TG_ID, type="private"),
                text=method.text,
            )
        return True


class Client:
    """Пользователь, который пишет боту и нажимает кнопки."""

    def __init__(self, dp, bot, fake):
        self.dp, self.bot, self.fake = dp, bot, fake
        self.update_id = itertools.count(1)
        self.user = User(id=TG_ID, is_bot=False, first_name="Тест")
        self.chat = Chat(id=TG_ID, type="private")

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


@pytest_asyncio.fixture
async def client(session_maker, monkeypatch):
    # хендлеры сами открывают сессии: направляем их в тестовую базу
    for module in (transaction, add_category, category_repository):
        monkeypatch.setattr(module, "async_session_maker", session_maker)

    # роутеры живут на уровне модуля и привязываются к диспетчеру один раз
    routers = (cancel.router, add_category.router, transaction.router)
    for router in routers:
        router._parent_router = None
    dp = Dispatcher(storage=MemoryStorage())
    for router in routers:
        dp.include_router(router)

    fake = FakeSession()
    bot = Bot(token="42:" + "A" * 35, session=fake)
    yield Client(dp, bot, fake)
    for router in routers:
        router._parent_router = None


@pytest_asyncio.fixture
async def world(session_maker):
    """Пользователь с картой и одной общей категорией «Еда»."""
    async with session_maker() as session:
        user, _ = await get_or_create_user(session, TG_ID)
        card = await create_account(session, user.id, "Карта", "card", "BYN")
        await set_active_account(session, user, card.id)
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        fun = await get_or_create_default_category(session, "🎉 Развлечения", "expense")
        # id берём до commit: после него объекты устаревают
        ids = {"user": user.id, "card": card.id, "food": food.id, "fun": fun.id}
        await session.commit()
        return ids


async def count_transactions(session_maker):
    async with session_maker() as session:
        return await session.scalar(select(func.count()).select_from(Transaction))


async def last_transaction(session_maker):
    async with session_maker() as session:
        result = await session.execute(
            select(Transaction).order_by(Transaction.id.desc())
        )
        return result.scalars().first()


async def test_unknown_description_asks_for_category(client, world, session_maker):
    await client.say("кофе 7")
    text, buttons = client.last
    assert "Выбери категорию" in text
    assert f"category:{world['food']}" in buttons
    assert "category_add" in buttons
    assert not any(b.startswith("date:") for b in buttons)  # даты тут больше нет
    assert await count_transactions(session_maker) == 0


async def test_chosen_category_goes_to_confirmation_not_straight_to_db(
    client, world, session_maker
):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    text, buttons = client.last
    assert "Всё верно?" in text and "🍔 Еда" in text
    assert buttons == [
        "entry:confirm",
        "cancel",
        "entry:date",
        "entry:category",
    ]
    assert "угадана" not in text
    assert await count_transactions(session_maker) == 0  # пока ничего не записано


async def test_confirm_creates_transaction_without_undo_button(
    client, world, session_maker
):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:confirm")
    text, buttons = client.last
    assert "Трата создана" in text
    assert buttons == []  # кнопки «Отменить» нет
    saved = await last_transaction(session_maker)
    assert (saved.amount, saved.description, saved.category_id) == (
        Decimal("7.00"),
        "кофе",
        world["food"],
    )


async def test_double_confirm_creates_only_one_transaction(
    client, world, session_maker
):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:confirm")
    await client.press("entry:confirm")  # второй клик по уже использованной кнопке
    assert await count_transactions(session_maker) == 1


async def test_guessed_category_skips_selection(client, world, session_maker):
    async with session_maker() as session:
        await create_transaction(
            session, world["card"], world["food"], "кофе", Decimal("5"), "expense"
        )
        await session.commit()
    await client.say("Кофе 7")
    text, buttons = client.last
    assert "Всё верно?" in text  # сразу окно подтверждения, без выбора категории
    assert "🍔 Еда" in text and "угадана" in text
    assert "entry:confirm" in buttons


async def test_change_category_from_confirmation(client, world, session_maker):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:category")
    text, buttons = client.last
    assert "Выбери категорию" in text
    assert "entry:back" in buttons  # можно вернуться, не выбирая
    await client.press(f"category:{world['fun']}")
    text, _ = client.last
    assert "🎉 Развлечения" in text and "Всё верно?" in text
    await client.press("entry:confirm")
    assert (await last_transaction(session_maker)).category_id == world["fun"]


async def test_change_date_with_button(client, world, session_maker):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:date")
    _, buttons = client.last
    assert buttons == ["date:yesterday", "date:today", "entry:back", "cancel"]
    await client.press("date:yesterday")
    text, _ = client.last
    assert "вчера" in text and "Всё верно?" in text
    await client.press("entry:confirm")
    assert (await last_transaction(session_maker)).date == date.today() - timedelta(1)


async def test_change_date_by_typing(client, world, session_maker):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:date")
    await client.say("01.09.2026")
    text, _ = client.last
    assert "01.09.2026" in text and "Всё верно?" in text
    await client.press("entry:confirm")
    assert (await last_transaction(session_maker)).date == date(2026, 9, 1)


async def test_future_date_is_rejected(client, world):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:date")
    future = (date.today() + timedelta(days=3)).strftime("%d.%m.%Y")
    await client.say(future)
    text, _ = client.last
    assert "ещё не наступила" in text


async def test_back_from_date_menu_returns_to_confirmation(client, world):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:date")
    await client.press("entry:back")
    text, _ = client.last
    assert "Всё верно?" in text


async def test_cancel_writes_nothing(client, world, session_maker):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("cancel")
    assert "отменено" in client.last[0]
    assert await count_transactions(session_maker) == 0


async def test_income_with_plus(client, world, session_maker):
    async with session_maker() as session:
        salary = await get_or_create_default_category(session, "💼 Зарплата", "income")
        salary_id = salary.id
        await session.commit()
    await client.say("+500 зарплата")
    text, buttons = client.last
    assert "Доход" in text and f"category:{salary_id}" in buttons
    assert f"category:{world['food']}" not in buttons  # категории расходов не показаны
    await client.press(f"category:{salary_id}")
    await client.press("entry:confirm")
    assert "Доход создан" in client.last[0]


async def test_foreign_category_id_in_button_is_rejected(client, world, session_maker):
    async with session_maker() as session:
        other, _ = await get_or_create_user(session, 999)
        foreign = Category(name="Чужая", owner_id=other.id, type="expense")
        session.add(foreign)
        await session.flush()
        foreign_id = foreign.id
        await session.commit()
    await client.say("кофе 7")
    await client.press(f"category:{foreign_id}")  # id подменили в кнопке
    assert "Выбери категорию" in client.last[0]  # дальше не пустило
    assert await count_transactions(session_maker) == 0


async def test_not_enough_money_on_cash_blocks_confirmation(
    client, world, session_maker
):
    async with session_maker() as session:
        cash = await create_account(session, world["user"], "Нал", "cash", "BYN")
        user, _ = await get_or_create_user(session, TG_ID)
        await set_active_account(session, user, cash.id)
        await session.commit()
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.press("entry:confirm")
    assert "Не хватает денег" in client.last[0]
    assert await count_transactions(session_maker) == 0


async def test_new_category_from_entry_returns_to_confirmation(
    client, world, session_maker
):
    await client.say("кофе 7")
    await client.press("category_add")
    await client.say("Кафе")
    await client.press("skip")  # без эмодзи
    text, buttons = client.last
    assert "Всё верно?" in text and "Кафе" in text
    assert "entry:confirm" in buttons
    assert await count_transactions(session_maker) == 0  # сразу не записали
    await client.press("entry:confirm")
    assert "Трата создана" in client.last[0]
    async with session_maker() as session:
        category = await session.get(
            Category, (await last_transaction(session_maker)).category_id
        )
        assert category.name == "Кафе"


async def test_old_undo_button_is_harmless(client, world):
    await client.press("undo:1:1")
    assert not client.fake.sent  # ответили только всплывающим окном, без сообщений


async def test_typing_text_while_confirming_gives_hint(client, world):
    await client.say("кофе 7")
    await client.press(f"category:{world['food']}")
    await client.say("что-то ещё")
    assert "Нажми одну из кнопок" in client.last[0]


@pytest.fixture(autouse=True)
def _no_real_network():
    # подстраховка: бот в тестах не должен ходить в интернет
    return None
