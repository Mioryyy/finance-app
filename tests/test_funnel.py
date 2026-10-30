"""/funnel для автора и дата регистрации пользователей."""

from datetime import datetime, timedelta
from decimal import Decimal

from flow_helpers import TG_ID
from sqlalchemy import select

from app.models.user import User
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user
from app.services.reminders import MINSK


async def make_user(session, telegram_id, created_at, operations=None):
    # operations=None — без счёта; число — счёт и столько трат
    user, _ = await get_or_create_user(session, telegram_id)
    user.created_at = created_at
    if operations is not None:
        account = await create_account(session, user.id, "Карта", "card", "BYN")
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        for _ in range(operations):
            await create_transaction(
                session, account.id, food.id, "кофе", Decimal(5), "expense"
            )


async def test_new_user_gets_a_registration_date(session_maker):
    async with session_maker() as session:
        user, _ = await get_or_create_user(session, 1)
        user_id = user.id
        await session.commit()
    async with session_maker() as session:
        created_at = await session.scalar(
            select(User.created_at).where(User.id == user_id)
        )
    assert created_at is not None


async def test_funnel_by_day_for_the_author(client, session_maker, monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", str(TG_ID))
    now = datetime.now(MINSK)
    async with session_maker() as session:
        await make_user(session, 1, now, operations=2)
        await make_user(session, 2, now, operations=0)
        await make_user(session, 3, now)  # без счёта
        await make_user(session, 4, now - timedelta(days=1), operations=1)
        await make_user(session, 5, now - timedelta(days=30), operations=1)  # давно
        await make_user(session, 6, None, operations=1)  # пришёл до колонки
        await session.commit()
    await client.say("/funnel")
    text = client.last[0]
    today = now.strftime("%d.%m")
    yesterday = (now - timedelta(days=1)).strftime("%d.%m")
    assert f"{today}        3    2   1  1" in text
    assert f"{yesterday}        1    1   1  0" in text
    assert (now - timedelta(days=30)).strftime("%d.%m") not in text
    assert "всего        6    5   4  1" in text
    assert text.index(today) < text.index(yesterday)  # свежие дни сверху


async def test_funnel_is_hidden_from_everyone_else(client, session_maker, monkeypatch):
    await client.say("/funnel")  # ADMIN_CHAT_ID не задан
    assert "Не знаю такой команды" in client.last[0]
    monkeypatch.setenv("ADMIN_CHAT_ID", "555")  # автор — кто-то другой
    await client.say("/funnel")
    assert "Не знаю такой команды" in client.last[0]
