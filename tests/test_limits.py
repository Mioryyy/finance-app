"""Лимиты на категории: предупреждения 80% и превышение, диалог /limits."""

from decimal import Decimal

from sqlalchemy import select

from app.models.limit import CategoryLimit
from app.repositories.limit_repository import delete_limit, set_limit
from app.services.limits import limit_warning_text


def test_no_warning_below_threshold():
    assert (
        limit_warning_text("Еда", Decimal("50"), Decimal("50"), Decimal("100"), "BYN")
        is None
    )


def test_warning_once_when_crossing_80_percent():
    text = limit_warning_text(
        "Еда", Decimal("85"), Decimal("35"), Decimal("100"), "BYN"
    )
    assert text.startswith("🟡 85% лимита на Еда")
    assert "осталось 15" in text
    # следующая трата внутри 80-99% уже не повторяет предупреждение
    assert (
        limit_warning_text("Еда", Decimal("90"), Decimal("5"), Decimal("100"), "BYN")
        is None
    )


def test_over_limit_warns_every_time():
    first = limit_warning_text(
        "Еда", Decimal("120"), Decimal("40"), Decimal("100"), "BYN"
    )
    again = limit_warning_text(
        "Еда", Decimal("130"), Decimal("10"), Decimal("100"), "BYN"
    )
    assert first.startswith("🔴 Лимит на Еда превышен")
    assert again.startswith("🔴 Лимит на Еда превышен")


def test_category_name_is_escaped():
    text = limit_warning_text(
        "<i>Еда", Decimal("100"), Decimal("1"), Decimal("100"), "BYN"
    )
    assert "&lt;i&gt;Еда" in text


async def limits_in_db(session_maker):
    async with session_maker() as session:
        return (await session.execute(select(CategoryLimit))).scalars().all()


async def test_create_limit_and_get_warnings(client, world, session_maker):
    await client.press("lim:new")
    await client.press(f"lim:cat:{world['food']}")
    await client.say("100")
    assert "Лимит сохранён" in client.last[0]
    (limit,) = await limits_in_db(session_maker)
    assert (limit.amount, limit.currency) == (Decimal("100.00"), "BYN")

    await client.say("обед 85")
    await client.press(f"category:{world['food']}")
    await client.press("entry:confirm")
    assert "85% лимита" in client.last[0]

    await client.say("ужин 30")
    await client.press(f"category:{world['food']}")
    await client.press("entry:confirm")
    assert "Лимит на 🍔 Еда превышен: 115" in client.last[0]


async def test_other_category_has_no_warning(client, world, session_maker):
    await client.press("lim:new")
    await client.press(f"lim:cat:{world['food']}")
    await client.say("10")
    await client.say("кино 50")
    await client.press(f"category:{world['fun']}")
    await client.press("entry:confirm")
    assert "лимит" not in client.last[0].lower()


async def test_limit_amount_is_validated(client, world, session_maker):
    await client.press("lim:new")
    await client.press(f"lim:cat:{world['food']}")
    await client.say("много")
    assert "сумму числом" in client.last[0]
    assert await limits_in_db(session_maker) == []


async def test_set_limit_twice_updates_and_delete_is_owner_only(world, session_maker):
    async with session_maker() as session:
        first = await set_limit(
            session, world["user"], world["food"], "BYN", Decimal("10")
        )
        second = await set_limit(
            session, world["user"], world["food"], "BYN", Decimal("20")
        )
        assert first.id == second.id and second.amount == Decimal("20")
        assert not await delete_limit(session, first.id, world["user"] + 1)
        assert await delete_limit(session, first.id, world["user"])
