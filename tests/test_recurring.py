"""Регулярные операции: расписание, диалог /recurring, вопрос «Добавить?»."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.account import Account
from app.models.recurring import RecurringPayment
from app.models.transaction import Transaction
from app.repositories.recurring_repository import delete_recurring
from app.services.recurring import (
    advance_due,
    due_token,
    first_due,
    next_due_after,
    parse_due_token,
    period_text,
    send_recurring_prompts,
    today_minsk,
    year_due,
)


def test_first_due_this_month_or_next():
    today = date(2026, 11, 10)
    assert first_due(15, today) == date(2026, 11, 15)
    assert first_due(10, today) == date(2026, 11, 10)  # сегодня ещё можно
    assert first_due(5, today) == date(2026, 12, 5)
    assert first_due(5, date(2026, 12, 20)) == date(2027, 1, 5)


def test_short_months_use_last_day():
    assert first_due(31, date(2026, 2, 1)) == date(2026, 2, 28)
    assert next_due_after(31, date(2026, 1, 31)) == date(2026, 2, 28)
    assert next_due_after(31, date(2026, 2, 28)) == date(2026, 3, 31)
    assert next_due_after(15, date(2026, 12, 15)) == date(2027, 1, 15)


def test_due_token_roundtrip():
    assert parse_due_token(due_token(date(2026, 11, 5))) == date(2026, 11, 5)
    assert parse_due_token("20261345") is None


async def payments(session_maker):
    async with session_maker() as session:
        return (await session.execute(select(RecurringPayment))).scalars().all()


async def transactions(session_maker):
    async with session_maker() as session:
        return (await session.execute(select(Transaction))).scalars().all()


async def card_balance(session_maker, card_id):
    async with session_maker() as session:
        return await session.scalar(
            select(Account.balance).where(Account.id == card_id)
        )


async def create_subscription(client, world, text="Spotify 5", day="15"):
    await client.press("rec:new")
    await client.press("rec:type:expense")
    await client.press(f"rec:cat:{world['fun']}")
    await client.say(text)
    await client.press("rec:per:month")
    await client.say(day)


async def test_create_recurring_asks_type_category_amount_day(
    client, world, session_maker
):
    await create_subscription(client, world)
    assert "Готово" in client.last[0]
    (payment,) = await payments(session_maker)
    assert (payment.description, payment.amount, payment.tx_type) == (
        "Spotify",
        Decimal("5.00"),
        "expense",
    )
    assert payment.day_of_month == 15
    assert payment.account_id == world["card"]
    assert payment.category_id == world["fun"]


async def test_bad_day_is_rejected(client, world, session_maker):
    await create_subscription(client, world, day="40")
    assert "от 1 до 31" in client.last[0]
    assert await payments(session_maker) == []


async def test_prompt_then_confirm_adds_once(client, world, session_maker):
    await create_subscription(client, world)
    (payment,) = await payments(session_maker)
    due = payment.next_due
    sent_before = len(client.fake.sent)

    # до дня платежа вопроса нет
    await send_recurring_prompts(client.bot, today=date(2000, 1, 1))
    assert len(client.fake.sent) == sent_before

    await send_recurring_prompts(client.bot, today=due)
    text, buttons = client.last
    assert "Добавить в историю?" in text and "Spotify" in text
    assert buttons == [
        f"rec:ok:{payment.id}:{due_token(due)}",
        f"rec:skip:{payment.id}:{due_token(due)}",
    ]
    # повторный запуск в тот же день не спрашивает второй раз
    count = len(client.fake.sent)
    await send_recurring_prompts(client.bot, today=due)
    assert len(client.fake.sent) == count

    await client.press(buttons[0])
    assert "Добавлено" in client.last[0]
    await client.press(buttons[0])  # двойное нажатие
    (transaction,) = await transactions(session_maker)
    assert (transaction.amount, transaction.date) == (Decimal("5.00"), due)
    assert await card_balance(session_maker, world["card"]) == Decimal("-5.00")
    (payment,) = await payments(session_maker)
    assert payment.next_due == next_due_after(15, due)


async def test_skip_does_not_create_transaction(client, world, session_maker):
    await create_subscription(client, world)
    (payment,) = await payments(session_maker)
    due = payment.next_due
    await send_recurring_prompts(client.bot, today=due)
    await client.press(f"rec:skip:{payment.id}:{due_token(due)}")
    assert "Пропущено" in client.last[0]
    assert await transactions(session_maker) == []
    (payment,) = await payments(session_maker)
    assert payment.next_due == next_due_after(15, due)


async def test_old_button_after_delete_is_harmless(client, world, session_maker):
    await create_subscription(client, world)
    (payment,) = await payments(session_maker)
    token = due_token(payment.next_due)
    async with session_maker() as session:
        assert await delete_recurring(session, payment.id, world["user"])
        await session.commit()
    await client.press(f"rec:ok:{payment.id}:{token}")
    assert await transactions(session_maker) == []


async def test_other_user_cannot_delete(world, session_maker):
    async with session_maker() as session:
        assert not await delete_recurring(session, 1, world["user"] + 1)


async def test_delete_user_data_removes_limits_and_recurring(
    client, world, session_maker
):
    from app.models.limit import CategoryLimit
    from app.repositories.limit_repository import set_limit
    from app.repositories.user_repository import delete_user_data

    await create_subscription(client, world)
    async with session_maker() as session:
        await set_limit(session, world["user"], world["food"], "BYN", Decimal("10"))
        await session.commit()
    async with session_maker() as session:
        await delete_user_data(session, world["user"])
        await session.commit()
    async with session_maker() as session:
        assert (await session.execute(select(RecurringPayment))).first() is None
        assert (await session.execute(select(CategoryLimit))).first() is None


# ---------- периоды: каждые N дней и раз в год ----------


class Payment:
    # минимальный платёж для проверки расчёта дат без базы
    def __init__(self, period, day_of_month=1, interval_days=None, anchor_month=None):
        self.period = period
        self.day_of_month = day_of_month
        self.interval_days = interval_days
        self.anchor_month = anchor_month


def test_every_30_days_does_not_stick_to_a_day_of_month():
    payment = Payment("days", interval_days=30)
    due = date(2026, 1, 15)
    dates = []
    for _ in range(3):
        due = advance_due(payment, due)
        dates.append(due)
    # месяцы разной длины: платёж «уезжает», в отличие от месячного
    assert dates == [date(2026, 2, 14), date(2026, 3, 16), date(2026, 4, 15)]


def test_yearly_and_leap_day():
    payment = Payment("year", day_of_month=29, anchor_month=2)
    assert advance_due(payment, date(2028, 2, 29)) == date(2029, 2, 28)
    assert advance_due(payment, date(2029, 2, 28)) == date(2030, 2, 28)
    assert year_due(5, 11, date(2026, 11, 4)) == date(2026, 11, 5)
    assert year_due(5, 11, date(2026, 11, 6)) == date(2027, 11, 5)


def test_monthly_still_works_through_advance_due():
    payment = Payment("month", day_of_month=31)
    assert advance_due(payment, date(2026, 1, 31)) == date(2026, 2, 28)


def test_period_text():
    assert period_text(Payment("days", interval_days=30)) == "каждые 30 дн."
    assert period_text(Payment("year", 5, anchor_month=11)) == "раз в год, 05.11"
    assert period_text(Payment("month", 15)) == "каждый месяц, 15-го числа"


async def start_dialog(client, world, text="VPN 10"):
    await client.press("rec:new")
    await client.press("rec:type:expense")
    await client.press(f"rec:cat:{world['fun']}")
    await client.say(text)


async def test_create_every_n_days(client, world, session_maker):
    await start_dialog(client, world)
    await client.press("rec:per:days")
    await client.say("0")
    assert "от 1 до" in client.last[0]
    await client.say("30")
    assert "Когда ближайший платёж" in client.last[0]
    await client.say("в пятницу")
    assert "Не понял" in client.last[0]
    await client.say("вчера")  # прошлое не подходит
    assert "Не понял или дата уже прошла" in client.last[0]
    await client.say("завтра")
    (payment,) = await payments(session_maker)
    assert (payment.period, payment.interval_days) == ("days", 30)
    assert payment.next_due == today_minsk() + timedelta(days=1)
    assert "каждые 30 дн." in client.last[0]


async def test_create_yearly(client, world, session_maker):
    await start_dialog(client, world, "Домен 12")
    await client.press("rec:per:year")
    await client.say("32.13")
    assert "Не понял" in client.last[0]
    await client.say("05.11")
    (payment,) = await payments(session_maker)
    assert (payment.period, payment.day_of_month, payment.anchor_month) == (
        "year",
        5,
        11,
    )
    assert payment.next_due >= today_minsk()


async def test_every_n_days_prompt_moves_by_exactly_n_days(
    client, world, session_maker
):
    await start_dialog(client, world)
    await client.press("rec:per:days")
    await client.say("30")
    await client.say("сегодня")
    (payment,) = await payments(session_maker)
    due = payment.next_due
    await send_recurring_prompts(client.bot, today=due)
    await client.press(f"rec:ok:{payment.id}:{due_token(due)}")
    (payment,) = await payments(session_maker)
    assert payment.next_due == due + timedelta(days=30)


# ---------- правка подписки ----------


async def test_edit_amount_applies_to_next_payment_only(client, world, session_maker):
    await create_subscription(client, world)
    (payment,) = await payments(session_maker)
    due = payment.next_due
    await send_recurring_prompts(client.bot, today=due)
    await client.press(f"rec:ok:{payment.id}:{due_token(due)}")  # старая цена 5

    await client.press(f"rec:open:{payment.id}")
    assert f"rec:amt:{payment.id}" in client.last[1]
    await client.press(f"rec:amt:{payment.id}")
    await client.say("много")
    assert "сумму числом" in client.last[0]
    await client.say("6,5")
    assert "Сумма изменена" in client.last[0]

    (payment,) = await payments(session_maker)
    assert payment.amount == Decimal("6.50")
    (old,) = await transactions(session_maker)
    assert old.amount == Decimal("5.00")  # уже записанное не изменилось


async def test_edit_next_due_is_asked_again(client, world, session_maker):
    await create_subscription(client, world)
    (payment,) = await payments(session_maker)
    due = payment.next_due
    await send_recurring_prompts(client.bot, today=due)  # вопрос ушёл
    new_due = due + timedelta(days=3)
    await client.press(f"rec:next:{payment.id}")
    await client.say("вчера")
    assert "дата уже прошла" in client.last[0]
    await client.say(new_due.strftime("%d.%m.%Y"))
    (payment,) = await payments(session_maker)
    assert payment.next_due == new_due
    # дата сдвинулась, значит спросить надо заново, когда она придёт
    count = len(client.fake.sent)
    await send_recurring_prompts(client.bot, today=new_due)
    assert len(client.fake.sent) == count + 1


async def test_edit_buttons_are_owner_only(client, world, session_maker):
    await client.press("rec:open:99999")
    await client.press("rec:amt:99999")
    assert not any("Напиши новую сумму" in sent[1] for sent in client.fake.sent)
