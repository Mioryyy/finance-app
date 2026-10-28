"""Диалог записи траты целиком: настоящие хендлеры, подменённый Telegram и БД finance_test."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from flow_helpers import TG_ID
from sqlalchemy import func, select

from app.bot.handlers import transaction
from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.transaction_repository import create_transaction
from app.repositories.user_repository import get_or_create_user, set_active_account


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


# --- категорию предлагает ИИ, когда история не помогла ---


@pytest.fixture
def ai(monkeypatch):
    """Включает ИИ и подменяет его ответ; запоминает, что ему отправили."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    class Fake:
        answer = None  # id категории, который «выберет» модель
        calls = []

    async def fake_guess(description, categories):
        Fake.calls.append((description, categories))
        return Fake.answer

    Fake.calls = []
    monkeypatch.setattr(transaction, "guess_category_with_ai", fake_guess)
    return Fake


async def test_ai_suggestion_skips_selection_and_is_marked(client, world, ai):
    ai.answer = world["food"]
    await client.say("шаурма 12")
    text, buttons = client.last
    assert "Всё верно?" in text and "🍔 Еда" in text
    assert "🤖" in text and "ИИ" in text  # пользователь видит, что это предложение ИИ
    assert "entry:confirm" in buttons
    assert "SendChatAction" in client.fake.other  # пока ИИ думал, бот «печатал»


async def test_ai_gets_only_description_and_own_type_categories(
    client, world, session_maker, ai
):
    async with session_maker() as session:
        salary = await get_or_create_default_category(session, "💼 Зарплата", "income")
        salary_id = salary.id
        await session.commit()
    ai.answer = world["food"]
    await client.say("шаурма 12")
    description, categories = ai.calls[0]
    assert description == "шаурма"  # без суммы
    ids = {cid for cid, _name in categories}
    assert world["food"] in ids and world["fun"] in ids
    assert salary_id not in ids  # для расхода категории дохода не отправляются


async def test_ai_not_sure_falls_back_to_category_choice(client, world, ai):
    ai.answer = None
    await client.say("шаурма 12")
    text, buttons = client.last
    assert "Выбери категорию" in text
    assert f"category:{world['food']}" in buttons


async def test_ai_is_not_asked_when_history_knows(client, world, session_maker, ai):
    async with session_maker() as session:
        await create_transaction(
            session, world["card"], world["food"], "кофе", Decimal("5"), "expense"
        )
        await session.commit()
    ai.answer = world["fun"]
    await client.say("кофе 7")
    text, _ = client.last
    assert "🍔 Еда" in text and "угадана по твоей истории" in text
    assert ai.calls == []  # история бесплатна и точнее: к ИИ не обращались


async def test_ai_is_not_asked_without_a_key(client, world, monkeypatch):
    called = []

    async def must_not_be_called(description, categories):
        called.append(description)

    monkeypatch.setattr(transaction, "guess_category_with_ai", must_not_be_called)
    await client.say("шаурма 12")  # ключа нет (его убирает conftest)
    assert "Выбери категорию" in client.last[0]
    assert called == []


async def test_ai_suggestion_can_be_changed_before_confirming(
    client, world, session_maker, ai
):
    ai.answer = world["food"]
    await client.say("шаурма 12")
    await client.press("entry:category")
    await client.press(f"category:{world['fun']}")
    text, _ = client.last
    assert "🎉 Развлечения" in text
    assert "🤖" not in text  # выбрал сам: пометки про ИИ больше нет
    await client.press("entry:confirm")
    assert (await last_transaction(session_maker)).category_id == world["fun"]


async def test_nothing_is_saved_until_ai_suggestion_is_confirmed(
    client, world, session_maker, ai
):
    ai.answer = world["food"]
    await client.say("шаурма 12")
    assert await count_transactions(session_maker) == 0
