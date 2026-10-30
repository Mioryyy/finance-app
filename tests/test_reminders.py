"""Вечернее сообщение: когда приходит, кому и что в нём."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from aiogram import Bot
from flow_helpers import FakeSession
from sqlalchemy import select

from app.models.user import User
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user, set_active_account
from app.services import reminders
from app.services.reminders import MINSK, seconds_until_next


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (19, 0, 3600),  # через час
        (19, 59, 60),
        (20, 0, 24 * 3600),  # ровно в 20:00 уже отправили: следующее завтра
        (21, 30, 22.5 * 3600),
        (0, 0, 20 * 3600),
    ],
)
def test_seconds_until_next(hour, minute, expected):
    now = datetime(2026, 10, 30, hour, minute, tzinfo=MINSK)
    assert seconds_until_next(now) == expected


def test_time_is_counted_in_minsk_not_utc():
    # 17:00 UTC — это 20:00 в Минске
    utc_now = datetime.fromisoformat("2026-10-30T16:00:00+00:00")
    assert seconds_until_next(utc_now) == 3600


async def make_user(session, telegram_id, reminders_on=True, with_account=True):
    user, _ = await get_or_create_user(session, telegram_id)
    user.reminders = reminders_on
    account_id = None
    if with_account:
        account = await create_account(session, user.id, "Карта", "card", "BYN")
        await set_active_account(session, user, account.id)
        account_id = account.id
    return user.id, account_id


@pytest.fixture
def evening(session_maker, monkeypatch):
    monkeypatch.setattr(reminders, "async_session_maker", session_maker)
    monkeypatch.setattr(reminders, "SEND_PAUSE_SECONDS", 0)
    fake = FakeSession()
    return Bot(token="42:" + "A" * 35, session=fake), fake


def messages_to(fake, chat_id):
    return [
        (text, keyboard)
        for (_kind, text, keyboard), chat in zip(fake.sent, fake.chats, strict=True)
        if chat == chat_id
    ]


async def test_who_gets_the_evening_message(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        await make_user(session, 1)
        await make_user(session, 2, reminders_on=False)
        await make_user(session, 3, with_account=False)  # до первой траты не дошёл
        await session.commit()
    sent = await reminders.send_evening_messages(bot)
    assert sent == 1
    assert set(fake.chats) == {1}
    ((text, keyboard),) = messages_to(fake, 1)
    assert "Сегодня ещё нет записей" in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        "remind:off"
    ]


async def test_counts_todays_records(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        _, account_id = await make_user(session, 1)
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        await create_transaction(
            session,
            account_id,
            food.id,
            "кофе",
            Decimal(5),
            "expense",
            datetime.now(MINSK).date(),
        )
        await session.commit()
    await reminders.send_evening_messages(bot)
    ((text, _),) = messages_to(fake, 1)
    assert "Сегодня записано операций: 1" in text


async def test_review_list_comes_instead_of_the_reminder(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        _, account_id = await make_user(session, 1)
        other = await get_or_create_default_category(session, "📦 Другое", "expense")
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        unsure = await create_transaction(
            session,
            account_id,
            other.id,
            "<b>билет</b>",
            Decimal(12),
            "expense",
            date(2026, 10, 29),
            needs_review=True,
        )
        await create_transaction(
            session,
            account_id,
            food.id,
            "кофе",
            Decimal(5),
            "expense",
            date(2026, 10, 29),
        )
        unsure_id = unsure.id
        await session.commit()
    await reminders.send_evening_messages(bot)
    ((text, keyboard),) = messages_to(fake, 1)
    assert "Проверь траты" in text
    assert "&lt;b&gt;билет&lt;/b&gt;" in text  # описание экранировано
    assert "кофе" not in text  # проверенные траты в список не попадают
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        f"tx:show:{unsure_id}",
        "remind:off",
    ]


async def test_blocked_user_gets_reminders_turned_off(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        await make_user(session, 1)
        await make_user(session, 2)
        await session.commit()
    fake.blocked.add(2)
    sent = await reminders.send_evening_messages(bot)
    assert sent == 1
    async with session_maker() as session:
        flags = dict(
            (await session.execute(select(User.telegram_id, User.reminders))).all()
        )
    assert flags == {1: True, 2: False}


async def test_delivery_error_does_not_stop_the_others(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        await make_user(session, 1)
        await make_user(session, 2)
        await session.commit()
    fake.fail_for.add(1)  # другая ошибка Telegram, не блокировка
    sent = await reminders.send_evening_messages(bot)
    assert sent == 1
    async with session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == 1))
    assert user.reminders is True  # из-за разовой ошибки не выключаем


# ---------- итог недели по воскресеньям ----------

SUNDAY = date(2026, 11, 1)  # неделя: пн 26.10 — вс 01.11


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "1 трату"),
        (2, "2 траты"),
        (5, "5 трат"),
        (11, "11 трат"),
        (21, "21 трату"),
        (24, "24 траты"),
    ],
)
def test_plural_spendings(count, expected):
    assert reminders.plural_spendings(count) == expected


async def spend(session, account_id, category_name, amount, day, tx_type="expense"):
    category = await get_or_create_default_category(session, category_name, tx_type)
    await create_transaction(
        session, account_id, category.id, "x", Decimal(amount), tx_type, day
    )


async def test_weekly_summary_on_sunday(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        _, card = await make_user(session, 1)
        await spend(session, card, "🍔 Еда", "20", date(2026, 10, 27))
        await spend(session, card, "🍔 Еда", "10", date(2026, 10, 30))
        await spend(session, card, "🚕 Транспорт", "12", date(2026, 10, 28))
        await spend(session, card, "🎉 Развлечения", "5", SUNDAY)
        await spend(session, card, "💰 Зарплата", "100", SUNDAY, "income")  # не трата
        await spend(session, card, "🍔 Еда", "40", date(2026, 10, 25))  # прошлая неделя
        await session.commit()
    await reminders.send_evening_messages(bot, today=SUNDAY)
    ((text, _),) = messages_to(fake, 1)
    assert "Итог недели" in text
    assert "<b>47.00 Br</b> на 4 траты" in text
    assert "Больше всего: 🍔 Еда — 30.00 Br" in text
    assert "Дальше: 🚕 Транспорт — 12.00 Br, 🎉 Развлечения — 5.00 Br" in text
    assert "Прошлая неделя: 40.00 Br" in text
    assert "Сегодня" not in text  # итог вместо обычного напоминания


async def test_no_summary_on_other_days(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        _, card = await make_user(session, 1)
        await spend(session, card, "🍔 Еда", "20", date(2026, 10, 27))
        await session.commit()
    await reminders.send_evening_messages(bot, today=date(2026, 10, 31))  # суббота
    ((text, _),) = messages_to(fake, 1)
    assert "Итог недели" not in text


async def test_currencies_are_not_added_together(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        user_id, card = await make_user(session, 1)
        dollars = await create_account(session, user_id, "Доллары", "card", "USD")
        await spend(session, card, "🍔 Еда", "20", date(2026, 10, 27))
        await spend(session, dollars.id, "🍔 Еда", "3", date(2026, 10, 27))
        await session.commit()
    await reminders.send_evening_messages(bot, today=SUNDAY)
    ((text, _),) = messages_to(fake, 1)
    assert "<b>20.00 Br</b> на 1 трату" in text
    assert "<b>3.00 $</b> на 1 трату" in text
    assert "23" not in text
    assert "Прошлая неделя" not in text  # тогда трат не было


async def test_empty_week_gets_the_usual_reminder(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        _, card = await make_user(session, 1)
        await spend(session, card, "🍔 Еда", "40", date(2026, 10, 25))  # только прошлая
        await session.commit()
    await reminders.send_evening_messages(bot, today=SUNDAY)
    ((text, _),) = messages_to(fake, 1)
    assert "Итог недели" not in text
    assert "Сегодня ещё нет записей" in text


async def test_summary_and_review_list_together(evening, session_maker):
    bot, fake = evening
    async with session_maker() as session:
        _, card = await make_user(session, 1)
        other = await get_or_create_default_category(session, "📦 Другое", "expense")
        unsure = await create_transaction(
            session,
            card,
            other.id,
            "билет",
            Decimal(12),
            "expense",
            date(2026, 10, 29),
            needs_review=True,
        )
        unsure_id = unsure.id
        await session.commit()
    await reminders.send_evening_messages(bot, today=SUNDAY)
    ((text, keyboard),) = messages_to(fake, 1)
    assert "Итог недели" in text and "Проверь траты" in text
    assert text.index("Итог недели") < text.index("Проверь траты")
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        f"tx:show:{unsure_id}",
        "remind:off",
    ]
