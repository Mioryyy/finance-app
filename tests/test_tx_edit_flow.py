"""Правка записанной операции: сумма, описание, дата, и дата в тексте записи."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.account import Account
from app.models.transaction import Transaction


async def saved(session_maker):
    async with session_maker() as session:
        result = await session.execute(select(Transaction).order_by(Transaction.id))
        return result.scalars().all()


async def balance(session_maker, account_id):
    async with session_maker() as session:
        return await session.scalar(
            select(Account.balance).where(Account.id == account_id)
        )


async def create_coffee(client, world, text="кофе 10"):
    await client.say(text)
    await client.press(f"category:{world['food']}")
    await client.press("entry:confirm")


async def test_edit_amount_moves_balance_by_difference(client, world, session_maker):
    await create_coffee(client, world)
    tx_id = (await saved(session_maker))[0].id
    assert await balance(session_maker, world["card"]) == Decimal("-10.00")
    await client.press(f"tx:open:{tx_id}")
    assert f"tx:amt:{tx_id}" in client.last[1]
    await client.press(f"tx:amt:{tx_id}")
    await client.say("25,5")
    assert "Сумма изменена" in client.last[0]
    assert (await saved(session_maker))[0].amount == Decimal("25.50")
    # было -10, трата выросла до 25,5: баланс -25,5, а не -35,5
    assert await balance(session_maker, world["card"]) == Decimal("-25.50")


async def test_edit_amount_rejects_garbage(client, world, session_maker):
    await create_coffee(client, world)
    tx_id = (await saved(session_maker))[0].id
    await client.press(f"tx:amt:{tx_id}")
    await client.say("много")
    assert "сумму числом" in client.last[0]
    assert (await saved(session_maker))[0].amount == Decimal("10.00")
    await client.say("-5")
    assert (await saved(session_maker))[0].amount == Decimal("10.00")


async def test_edit_description_and_date(client, world, session_maker):
    await create_coffee(client, world)
    tx_id = (await saved(session_maker))[0].id
    await client.press(f"tx:desc:{tx_id}")
    await client.say("латте")
    assert (await saved(session_maker))[0].description == "латте"
    await client.press(f"tx:date:{tx_id}")
    await client.say("вчера")
    assert (await saved(session_maker))[0].date == date.today() - timedelta(days=1)
    await client.press(f"tx:date:{tx_id}")
    await client.say("01.01.2999")
    assert "ещё не наступила" in client.last[0]
    assert (await saved(session_maker))[0].date == date.today() - timedelta(days=1)


async def test_edit_is_limited_to_owner(client, world, session_maker):
    await create_coffee(client, world)
    tx_id = (await saved(session_maker))[0].id
    await client.press(f"tx:amt:{tx_id + 999}")
    assert not any("Напиши новую сумму" in sent[1] for sent in client.fake.sent)


async def test_date_in_text_goes_to_confirmation(client, world, session_maker):
    await client.say("вчера кофе 5")
    await client.press(f"category:{world['food']}")
    assert "вчера" in client.last[0]
    await client.press("entry:confirm")
    saved_tx = (await saved(session_maker))[0]
    assert saved_tx.date == date.today() - timedelta(days=1)
    assert saved_tx.amount == Decimal("5.00")


async def test_amount_first_in_text(client, world, session_maker):
    await client.say("5 кофе")
    await client.press(f"category:{world['food']}")
    await client.press("entry:confirm")
    saved_tx = (await saved(session_maker))[0]
    assert (saved_tx.description, saved_tx.amount) == ("кофе", Decimal("5.00"))


async def test_future_date_in_text_is_rejected(client, world, session_maker):
    await client.say("кофе 5 01.01.2999")
    assert "ещё не наступила" in client.last[0]
    assert await saved(session_maker) == []
