"""Первый запуск: /start → валюта одной кнопкой → счёт «Карта» и кнопки его правки."""

import asyncio
import contextlib
from datetime import date
from decimal import Decimal

from flow_helpers import TG_ID
from sqlalchemy import func, select, text

from app.models.account import Account
from app.models.user import User
from app.repositories import user_repository
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import (
    create_first_account,
    get_or_create_user,
    set_active_account,
)

CURRENCY_BUTTONS = ["onboard:BYN", "onboard:RUB", "onboard:USD", "onboard:EUR"]


async def my_accounts(session_maker, telegram_id=TG_ID):
    async with session_maker() as session:
        result = await session.execute(
            select(Account)
            .join(User, User.id == Account.owner_id)
            .where(User.telegram_id == telegram_id)
            .order_by(Account.id)
        )
        return result.scalars().all()


async def active_account_id(session_maker):
    async with session_maker() as session:
        return await session.scalar(
            select(User.active_account_id).where(User.telegram_id == TG_ID)
        )


async def onboard(client, currency="BYN"):
    await client.say("/start")
    await client.press(f"onboard:{currency}")


def edit_buttons(account_id):
    return [
        f"acedit:name:{account_id}",
        f"acedit:type:{account_id}",
        f"acedit:bal:{account_id}",
    ]


# ---------- первый запуск ----------


async def test_new_user_is_asked_only_for_currency(client, session_maker):
    await client.say("/start")
    text, buttons = client.last
    assert "валюте" in text
    assert buttons == CURRENCY_BUTTONS
    assert await my_accounts(session_maker) == []  # пока ничего не создано


async def test_currency_button_creates_an_active_card(client, session_maker):
    await onboard(client, "RUB")
    (account,) = await my_accounts(session_maker)
    assert (account.name, account.type, account.currency) == ("Карта", "card", "RUB")
    assert account.balance == Decimal("0")
    assert await active_account_id(session_maker) == account.id
    text, buttons = client.last
    assert "кофе 5" in text  # сразу подсказываем первую трату
    assert buttons == edit_buttons(account.id)


async def test_first_expense_right_after_onboarding(client, session_maker):
    await onboard(client)
    await client.say("кофе 5")
    # трата не упала с «не хватает денег»: у карты при балансе 0 можно уйти в минус
    assert "Выбери категорию" in client.last[0] or "Всё верно?" in client.last[0]


async def test_fake_currency_is_rejected(client, session_maker):
    await client.say("/start")
    await client.press("onboard:XYZ")
    assert await my_accounts(session_maker) == []


async def test_second_press_does_not_create_a_second_account(client, session_maker):
    await onboard(client)
    await client.press("onboard:USD")  # старая кнопка
    assert len(await my_accounts(session_maker)) == 1


async def warm_up_two_connections(session_maker):
    # новое соединение с базой в Docker открывается секунды; заранее держим два
    # в пуле, чтобы обе «одновременные» сессии и правда начали сразу
    both_open = asyncio.Barrier(2)

    async def hold():
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
            await both_open.wait()

    await asyncio.gather(hold(), hold())


async def test_simultaneous_first_accounts_create_one(session_maker, monkeypatch):
    # два нажатия «BYN» одновременно, каждое в своей сессии базы. Первое создание
    # счёта ждёт, пока второе нажатие тоже до него дойдёт (не дольше секунды):
    # без блокировки оба прошли бы проверку «счёта ещё нет» и создали два счёта,
    # с блокировкой второе ждёт commit первого и видит готовый счёт
    async with session_maker() as session:
        await get_or_create_user(session, TG_ID)
        await session.commit()
    await warm_up_two_connections(session_maker)
    original = user_repository.create_account
    arrived = []
    both_arrived = asyncio.Event()

    async def slow_create_account(*args, **kwargs):
        arrived.append(1)
        if len(arrived) == 2:
            both_arrived.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both_arrived.wait(), timeout=1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(user_repository, "create_account", slow_create_account)

    async def press():
        async with session_maker() as session:
            user, _ = await get_or_create_user(session, TG_ID)
            account = await create_first_account(session, user, "BYN")
            await session.commit()
            return account is not None

    assert sorted(await asyncio.gather(press(), press())) == [False, True]
    assert len(await my_accounts(session_maker)) == 1


async def test_returning_user_is_welcomed_back(client, session_maker):
    await onboard(client)
    await client.say("/start")
    text, buttons = client.last
    assert "С возвращением" in text
    assert buttons == []


async def test_create_account_still_asks_for_a_name(client, session_maker):
    await onboard(client)
    await client.say("/create_account")
    assert "Как назовём счёт?" in client.last[0]


# ---------- название ----------


async def test_rename(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    await client.press(f"acedit:name:{account.id}")
    assert "Как назовём" in client.last[0]
    await client.say("  Приорбанк  ")
    (account,) = await my_accounts(session_maker)
    assert account.name == "Приорбанк"
    text, buttons = client.last
    assert "Приорбанк" in text and buttons == edit_buttons(account.id)


async def test_too_long_name_is_rejected_and_asked_again(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    await client.press(f"acedit:name:{account.id}")
    await client.say("а" * 21)
    assert "20" in client.last[0]
    await client.say("<b>Мешок</b>")
    (account,) = await my_accounts(session_maker)
    assert account.name == "<b>Мешок</b>"  # хранится как есть
    assert "&lt;b&gt;Мешок&lt;/b&gt;" in client.last[0]  # а в сообщении экранировано


async def test_cancel_while_renaming(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    await client.press(f"acedit:name:{account.id}")
    await client.say("/cancel")
    await client.say("кофе 5")  # это уже трата, а не новое название
    (account,) = await my_accounts(session_maker)
    assert account.name == "Карта"


# ---------- тип ----------


async def test_change_type(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    await client.press(f"acedit:type:{account.id}")
    assert client.last[1] == [
        f"acedit:settype:{account.id}:card",
        f"acedit:settype:{account.id}:cash",
        f"acedit:settype:{account.id}:crypto",
        f"acedit:back:{account.id}",
    ]
    await client.press(f"acedit:settype:{account.id}:cash")
    (account,) = await my_accounts(session_maker)
    assert account.type == "cash"
    assert client.last[1] == edit_buttons(account.id)


async def test_fake_type_is_rejected(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    await client.press(f"acedit:settype:{account.id}:gold")
    (account,) = await my_accounts(session_maker)
    assert account.type == "card"


async def test_card_in_minus_cannot_become_cash(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    async with session_maker() as session:
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        await create_transaction(
            session,
            account.id,
            food.id,
            "кофе",
            Decimal(5),
            "expense",
            date.today(),  # noqa: DTZ011
        )
        await session.commit()
    await client.press(f"acedit:settype:{account.id}:cash")
    (account,) = await my_accounts(session_maker)
    assert account.type == "card" and account.balance == Decimal("-5")


# ---------- остаток ----------


async def test_set_starting_balance(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    await client.press(f"acedit:bal:{account.id}")
    assert "Сколько сейчас" in client.last[0]
    await client.say("абв")
    assert "числом" in client.last[0]
    await client.say("-5")
    assert "числом" in client.last[0]
    await client.say("250,50")
    (account,) = await my_accounts(session_maker)
    assert account.balance == Decimal("250.50")
    assert "250.50" in client.last[0]


async def test_balance_is_locked_after_the_first_operation(client, session_maker):
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    async with session_maker() as session:
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        await create_transaction(
            session,
            account.id,
            food.id,
            "кофе",
            Decimal(5),
            "expense",
            date.today(),  # noqa: DTZ011
        )
        await session.commit()
    sent_before = len(client.fake.sent)
    await client.press(f"acedit:bal:{account.id}")
    assert len(client.fake.sent) == sent_before  # только всплывающее «нельзя»
    await client.say("100")  # бот не ждал сумму: это не остаток
    (account,) = await my_accounts(session_maker)
    assert account.balance == Decimal("-5")


async def test_balance_rechecked_when_the_amount_arrives(client, session_maker):
    # кнопку нажали до первой траты, а сумму прислали уже после
    await onboard(client)
    (account,) = await my_accounts(session_maker)
    await client.press(f"acedit:bal:{account.id}")
    async with session_maker() as session:
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        await create_transaction(
            session,
            account.id,
            food.id,
            "кофе",
            Decimal(5),
            "expense",
            date.today(),  # noqa: DTZ011
        )
        await session.commit()
    await client.say("100")
    (account,) = await my_accounts(session_maker)
    assert account.balance == Decimal("-5")
    assert "до первой операции" in client.last[0]


# ---------- чужие счета ----------


async def test_someone_elses_account_is_not_touched(client, session_maker):
    await onboard(client)
    async with session_maker() as session:
        stranger, _ = await get_or_create_user(session, 999)
        their = await create_account(session, stranger.id, "Чужой", "card", "BYN")
        await set_active_account(session, stranger, their.id)
        their_id = their.id
        await session.commit()
    sent_before = len(client.fake.sent)
    for action in ("name", "type", "bal", "back"):
        await client.press(f"acedit:{action}:{their_id}")
    await client.press(f"acedit:settype:{their_id}:cash")
    assert len(client.fake.sent) == sent_before
    (their,) = await my_accounts(session_maker, telegram_id=999)
    assert (their.name, their.type, their.balance) == ("Чужой", "card", Decimal("0"))


async def test_only_one_user_row_per_person(client, session_maker):
    await onboard(client)
    await client.say("/start")
    async with session_maker() as session:
        count = await session.scalar(
            select(func.count()).select_from(User).where(User.telegram_id == TG_ID)
        )
    assert count == 1
