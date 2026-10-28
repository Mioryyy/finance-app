"""Команда /delete_my_data целиком: настоящие хендлеры, подменённый Telegram, БД finance_test."""

from datetime import date
from decimal import Decimal

from flow_helpers import TG_ID, Client
from sqlalchemy import func, select

from app.models.category import Category
from app.models.user import User
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import (
    count_user_data,
    get_or_create_user,
    get_user,
)

OTHER_ID = 999


async def add_other_user(session_maker):
    """Второй пользователь со счётом и операцией: его данные трогать нельзя."""
    async with session_maker() as session:
        user, _ = await get_or_create_user(session, OTHER_ID)
        account = await create_account(
            session, user.id, "Чужой", "card", "BYN", Decimal("100")
        )
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        await create_transaction(
            session, account.id, food.id, "кофе", Decimal("5"), "expense", date.today()
        )
        user_id = user.id
        await session.commit()
        return user_id


async def counts_for(session_maker, telegram_id):
    async with session_maker() as session:
        user = await get_user(session, telegram_id)
        if user is None:
            return None
        return await count_user_data(session, user.id)


async def test_command_shows_what_will_be_deleted_and_asks_to_confirm(
    client, world, session_maker
):
    await client.say("/delete_my_data")
    text, buttons = client.last
    assert "Удалить все твои данные?" in text
    assert "счетов: 1" in text and "операций: 0" in text
    assert "резервных копиях" in text  # честно про дампы на сервере
    assert buttons == ["deldata:confirm", "cancel"]
    # пока не подтвердили, ничего не удалено
    assert (await counts_for(session_maker, TG_ID))["accounts"] == 1


async def test_confirm_deletes_everything_of_the_user(client, world, session_maker):
    async with session_maker() as session:
        await create_transaction(
            session, world["card"], world["food"], "кофе", Decimal("5"), "expense"
        )
        await session.commit()
    await client.say("/delete_my_data")
    assert "операций: 1" in client.last[0]
    await client.press("deldata:confirm")
    text, buttons = client.last
    assert "Все твои данные удалены" in text
    assert buttons == []
    assert await counts_for(session_maker, TG_ID) is None  # профиля больше нет


async def test_shared_categories_survive_the_deletion(client, world, session_maker):
    await client.say("/delete_my_data")
    await client.press("deldata:confirm")
    async with session_maker() as session:
        shared = await session.scalar(
            select(func.count())
            .select_from(Category)
            .where(Category.owner_id.is_(None))
        )
    assert shared == 2  # «Еда» и «Развлечения» принадлежат всем


async def test_only_the_one_who_confirms_loses_data(client, world, session_maker):
    other_id = await add_other_user(session_maker)
    await client.say("/delete_my_data")
    await client.press("deldata:confirm")
    assert await counts_for(session_maker, TG_ID) is None
    async with session_maker() as session:
        assert await count_user_data(session, other_id) == {
            "accounts": 1,
            "transactions": 1,
            "transfers": 0,
            "categories": 0,
        }
        assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_cancel_keeps_the_data(client, world, session_maker):
    await client.say("/delete_my_data")
    await client.press("cancel")
    assert "Действие отменено" in client.last[0]
    assert (await counts_for(session_maker, TG_ID))["accounts"] == 1


async def test_second_click_on_confirm_is_harmless(client, world, session_maker):
    await client.say("/delete_my_data")
    await client.press("deldata:confirm")
    sent = len(client.fake.sent)
    await client.press("deldata:confirm")  # повторное нажатие
    assert len(client.fake.sent) == sent  # новых сообщений нет, только всплывашка
    assert await counts_for(session_maker, TG_ID) is None


async def test_stale_confirm_button_deletes_nothing(client, world, session_maker):
    # кнопка из старого сообщения: состояния подтверждения уже нет
    await client.press("deldata:confirm")
    assert (await counts_for(session_maker, TG_ID))["accounts"] == 1


async def test_a_stranger_has_nothing_to_delete_and_gets_no_profile(
    client, world, session_maker
):
    stranger = Client(client.dp, client.bot, client.fake, telegram_id=555)
    await stranger.say("/delete_my_data")
    assert "нет твоих данных" in stranger.last[0]
    assert stranger.last[1] == []
    assert await counts_for(session_maker, 555) is None  # запись не создана


async def test_command_works_in_the_middle_of_another_dialog(
    client, world, session_maker
):
    await client.say("кофе 7")  # бот ждёт выбор категории
    await client.say("/delete_my_data")
    text, buttons = client.last
    assert "Удалить все твои данные?" in text
    assert "deldata:confirm" in buttons
    await client.press("deldata:confirm")
    assert await counts_for(session_maker, TG_ID) is None


async def test_user_can_start_again_after_deletion(client, world, session_maker):
    await client.say("/delete_my_data")
    await client.press("deldata:confirm")
    async with session_maker() as session:
        user, is_new = await get_or_create_user(session, TG_ID)
        assert is_new
        assert user.active_account_id is None
