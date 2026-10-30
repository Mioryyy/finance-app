"""Быстрый ввод, /settings и карточка уже записанной операции (кнопки tx:*)."""

from datetime import date
from decimal import Decimal

from flow_helpers import TG_ID
from sqlalchemy import func, select

from app.models.account import Account
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user


async def count_transactions(session_maker):
    async with session_maker() as session:
        return await session.scalar(select(func.count()).select_from(Transaction))


async def last_transaction(session_maker):
    async with session_maker() as session:
        result = await session.execute(
            select(Transaction).order_by(Transaction.id.desc())
        )
        return result.scalars().first()


async def get_user_row(session_maker):
    async with session_maker() as session:
        return await session.scalar(select(User).where(User.telegram_id == TG_ID))


async def balance(session_maker, account_id):
    async with session_maker() as session:
        return await session.scalar(
            select(Account.balance).where(Account.id == account_id)
        )


async def enable_quick(session_maker):
    async with session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == TG_ID))
        user.quick_entry = True
        await session.commit()


async def add_transaction(
    session_maker, account_id, category_id, description, amount, needs_review=False
):
    async with session_maker() as session:
        transaction = await create_transaction(
            session,
            account_id,
            category_id,
            description,
            Decimal(amount),
            "expense",
            date.today(),  # noqa: DTZ011
            needs_review=needs_review,
        )
        transaction_id = transaction.id
        await session.commit()
        return transaction_id


async def add_other_category(session_maker, name="📦 Другое", category_type="expense"):
    async with session_maker() as session:
        category = await get_or_create_default_category(session, name, category_type)
        category_id = category.id
        await session.commit()
        return category_id


# ---------- /settings ----------


async def test_settings_shows_both_toggles(client, world):
    await client.say("/settings")
    text, buttons = client.last
    assert "Быстрый ввод" in text and "Напоминание" in text
    assert buttons == ["settings:quick_entry", "settings:reminders"]


async def test_toggles_change_the_user_flags(client, world, session_maker):
    user = await get_user_row(session_maker)
    assert user.quick_entry is False and user.reminders is True  # значения по умолчанию
    await client.say("/settings")
    await client.press("settings:quick_entry")
    await client.press("settings:reminders")
    user = await get_user_row(session_maker)
    assert user.quick_entry is True and user.reminders is False
    await client.press("settings:quick_entry")
    assert (await get_user_row(session_maker)).quick_entry is False


async def test_unknown_setting_from_a_button_is_ignored(client, world, session_maker):
    await client.press("settings:active_account_id")  # подделанная кнопка
    user = await get_user_row(session_maker)
    assert user.quick_entry is False and user.reminders is True


async def test_turn_off_reminders_from_the_evening_message(
    client, world, session_maker
):
    await client.press("remind:off")
    assert (await get_user_row(session_maker)).reminders is False
    assert "Напоминания выключены" in client.last[0]


# ---------- быстрый ввод ----------


async def test_quick_entry_is_off_by_default(client, world, session_maker):
    await add_transaction(session_maker, world["card"], world["food"], "кофе", "5")
    await client.say("кофе 7")
    assert "Всё верно?" in client.last[0]
    assert await count_transactions(session_maker) == 1  # новая ещё не записана


async def test_quick_entry_saves_at_once_when_history_knows_the_category(
    client, world, session_maker
):
    await add_transaction(session_maker, world["card"], world["food"], "кофе", "5")
    await enable_quick(session_maker)
    await client.say("кофе 7")
    assert await count_transactions(session_maker) == 2
    saved = await last_transaction(session_maker)
    assert saved.category_id == world["food"] and saved.amount == Decimal("7")
    assert saved.needs_review is False  # история — уверенная догадка
    text, buttons = client.last
    assert text.startswith("⚡") and "🍔 Еда" in text and "вечером" not in text
    assert buttons == [f"tx:open:{saved.id}"]
    assert await balance(session_maker, world["card"]) == Decimal("-12")


async def test_quick_entry_unknown_description_goes_to_other_for_review(
    client, world, session_maker
):
    other = await add_other_category(session_maker)
    await enable_quick(session_maker)
    await client.say("билет 12")  # истории нет, ИИ выключен в тестах
    saved = await last_transaction(session_maker)
    assert saved.category_id == other
    assert saved.needs_review is True
    assert "вечером" in client.last[0]


async def test_quick_entry_without_other_category_asks_as_usual(
    client, world, session_maker
):
    await enable_quick(session_maker)
    await client.say("билет 12")
    assert "Выбери категорию" in client.last[0]
    assert await count_transactions(session_maker) == 0


async def test_unusual_amount_still_asks_for_confirmation(client, world, session_maker):
    await add_transaction(session_maker, world["card"], world["food"], "кофе", "5")
    await enable_quick(session_maker)
    await client.say("кофе 1000")  # опечатка вместо 10.00
    text, buttons = client.last
    assert "Всё верно?" in text and "больше обычной" in text
    assert "entry:confirm" in buttons
    assert await count_transactions(session_maker) == 1
    await client.press("entry:confirm")
    assert await count_transactions(session_maker) == 2  # подтвердил — записано


async def test_big_amount_without_history_asks_for_confirmation(
    client, world, session_maker
):
    await add_other_category(session_maker)
    await enable_quick(session_maker)
    await client.say("ноутбук 2000")
    assert "Всё верно?" in client.last[0]
    assert await count_transactions(session_maker) == 0


async def test_quick_entry_income_uses_income_other(client, world, session_maker):
    income_other = await add_other_category(session_maker, "🎉 Другое", "income")
    await enable_quick(session_maker)
    await client.say("+50 подарок")
    saved = await last_transaction(session_maker)
    assert saved.category_id == income_other
    assert await balance(session_maker, world["card"]) == Decimal("50")


# ---------- карточка операции ----------


async def test_edit_button_opens_the_card(client, world, session_maker):
    tx = await add_transaction(
        session_maker, world["card"], world["food"], "кофе", "5", needs_review=True
    )
    await client.press(f"tx:open:{tx}")
    text, buttons = client.last
    assert "кофе" in text and "Проверь категорию" in text
    assert buttons == [f"tx:ok:{tx}", f"tx:cat:{tx}", f"tx:del:{tx}"]


async def test_ok_clears_the_review_flag(client, world, session_maker):
    tx = await add_transaction(
        session_maker, world["card"], world["food"], "кофе", "5", needs_review=True
    )
    await client.press(f"tx:ok:{tx}")
    assert (await last_transaction(session_maker)).needs_review is False
    assert "Проверено" in client.last[0]


async def test_change_category(client, world, session_maker):
    tx = await add_transaction(
        session_maker, world["card"], world["food"], "кино", "12", needs_review=True
    )
    await client.press(f"tx:cat:{tx}")
    assert f"tx:set:{tx}:{world['fun']}" in client.last[1]
    await client.press(f"tx:set:{tx}:{world['fun']}")
    saved = await last_transaction(session_maker)
    assert saved.category_id == world["fun"] and saved.needs_review is False
    assert await balance(session_maker, world["card"]) == Decimal(
        "-12"
    )  # баланс тот же


async def test_category_of_another_type_is_rejected(client, world, session_maker):
    income = await add_other_category(session_maker, "💰 Зарплата", "income")
    tx = await add_transaction(session_maker, world["card"], world["food"], "кофе", "5")
    await client.press(f"tx:set:{tx}:{income}")  # подделанная кнопка
    assert (await last_transaction(session_maker)).category_id == world["food"]


async def test_delete_restores_the_balance(client, world, session_maker):
    tx = await add_transaction(session_maker, world["card"], world["food"], "кофе", "5")
    await client.press(f"tx:del:{tx}")
    assert client.last[1] == [f"tx:delok:{tx}", f"tx:open:{tx}"]
    await client.press(f"tx:delok:{tx}")
    assert await count_transactions(session_maker) == 0
    assert await balance(session_maker, world["card"]) == Decimal("0")
    await client.press(f"tx:delok:{tx}")  # повторное нажатие ничего не ломает
    assert await balance(session_maker, world["card"]) == Decimal("0")


async def test_someone_elses_transaction_is_not_touched(client, world, session_maker):
    async with session_maker() as session:
        stranger, _ = await get_or_create_user(session, 999)
        their_card = await create_account(session, stranger.id, "Чужая", "card", "BYN")
        their_card_id = their_card.id
        await session.commit()
    their_tx = await add_transaction(
        session_maker, their_card_id, world["food"], "чужое", "5", needs_review=True
    )
    sent_before = len(client.fake.sent)
    for action in ("open", "ok", "cat", "del", "delok"):
        await client.press(f"tx:{action}:{their_tx}")
    await client.press(f"tx:set:{their_tx}:{world['fun']}")
    assert len(client.fake.sent) == sent_before  # ничего не показали и не изменили
    saved = await last_transaction(session_maker)
    assert saved.id == their_tx and saved.needs_review is True
    assert saved.category_id == world["food"]
    assert await balance(session_maker, their_card_id) == Decimal("-5")
