"""Команда /feedback целиком: отзыв пересылается автору, с ограничениями и анонимностью."""

import asyncio

import pytest
from flow_helpers import TG_ID

from app.bot.handlers import feedback
from app.constants import FEEDBACK_COOLDOWN_SECONDS, FEEDBACK_MAX_LENGTH

ADMIN_ID = -100555  # чат автора (у групп id отрицательные)


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", str(ADMIN_ID))
    return ADMIN_ID


@pytest.fixture
def clock(monkeypatch):
    """Управляемое время: now() возвращает clock.t."""

    class Clock:
        t = 1000.0

    monkeypatch.setattr(feedback, "now", lambda: Clock.t)
    return Clock


def sent_to(client, chat_id):
    """Тексты всех сообщений, которые бот отправил в этот чат."""
    return [
        text
        for (_kind, text, _kb), chat in zip(
            client.fake.sent, client.fake.chats, strict=True
        )
        if chat == chat_id
    ]


async def send(client, text, how="feedback:named"):
    await client.say("/feedback")
    await client.say(text)
    await client.press(how)


async def test_command_asks_for_the_text(client, admin):
    await client.say("/feedback")
    assert "Напиши одним сообщением" in client.last[0]
    assert str(FEEDBACK_MAX_LENGTH) in client.last[0]


async def test_text_leads_to_the_choice_of_name_or_anonymous(client, admin):
    await client.say("/feedback")
    await client.say("Было бы здорово добавить бюджеты")
    text, buttons = client.last
    assert "Как отправить?" in text
    assert buttons == ["feedback:named", "feedback:anonymous", "cancel"]
    assert sent_to(client, admin) == []  # пока не выбрали, автору ничего не ушло


async def test_named_feedback_reaches_the_author_with_the_sender(client, admin):
    await send(client, "Не хватает графиков")
    (message,) = sent_to(client, admin)
    assert "Новый отзыв" in message and "Не хватает графиков" in message
    assert f"tg://user?id={TG_ID}" in message  # автор может открыть чат и ответить
    assert f"id {TG_ID}" in message
    text, buttons = client.last
    assert "Отзыв отправлен" in text
    assert buttons == []


async def test_anonymous_feedback_hides_who_wrote_it(client, admin):
    await send(client, "Анонимная мысль", how="feedback:anonymous")
    (message,) = sent_to(client, admin)
    assert "Анонимная мысль" in message
    assert "анонимно" in message
    assert str(TG_ID) not in message  # ни id, ни ссылки на человека
    assert "tg://" not in message


async def test_html_in_the_feedback_is_escaped(client, admin):
    await send(client, "<b>жирно</b> & <a href='x'>ссылка</a>")
    (message,) = sent_to(client, admin)
    assert "&lt;b&gt;жирно&lt;/b&gt;" in message
    assert "<a href='x'>" not in message  # чужая разметка не должна «ожить»


async def test_nothing_goes_to_anyone_but_the_author(client, admin):
    await send(client, "Привет")
    # все сообщения бота: либо пользователю (TG_ID), либо автору (ADMIN_ID)
    assert set(client.fake.chats) <= {TG_ID, ADMIN_ID, None}


async def test_feedback_is_off_without_admin_chat_id(client, world):
    await client.say("/feedback")  # ADMIN_CHAT_ID не задан
    assert "выключен" in client.last[0]
    # и бот не ждёт отзыв: следующий текст разбирается как обычная запись
    await client.say("привет")
    assert "Не могу распознать сумму" in client.last[0]


async def test_broken_admin_chat_id_also_switches_it_off(client, monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "не число")
    await client.say("/feedback")
    assert "выключен" in client.last[0]


async def test_too_long_text_is_rejected_but_the_dialog_continues(client, admin):
    await client.say("/feedback")
    await client.say("а" * (FEEDBACK_MAX_LENGTH + 1))
    assert "Слишком длинно" in client.last[0]
    await client.say("а" * FEEDBACK_MAX_LENGTH)  # ровно по лимиту проходит
    assert "Как отправить?" in client.last[0]


async def test_blank_text_is_rejected(client, admin):
    await client.say("/feedback")
    await client.say("   ")
    assert "текстом" in client.last[0]


async def test_cooldown_blocks_a_second_feedback_until_it_expires(client, admin, clock):
    await send(client, "первый")
    await client.say("/feedback")
    assert "Подожди" in client.last[0]
    clock.t += FEEDBACK_COOLDOWN_SECONDS - 1
    await client.say("/feedback")
    assert "Подожди 1 с" in client.last[0]
    clock.t += 1
    await client.say("/feedback")
    assert "Напиши одним сообщением" in client.last[0]


async def test_cooldown_is_checked_again_when_sending(client, admin, clock):
    # пользователь успел начать два отзыва подряд: второй не должен уйти
    await client.say("/feedback")
    await client.say("первый")
    feedback.last_sent[TG_ID] = clock.t  # отзыв «ушёл» из другого диалога
    await client.press("feedback:named")
    assert "Подожди" in client.last[0]
    assert sent_to(client, admin) == []


async def test_cancel_button_sends_nothing(client, admin):
    await client.say("/feedback")
    await client.say("передумал")
    await client.press("cancel")
    assert "Действие отменено" in client.last[0]
    assert sent_to(client, admin) == []


async def test_cancel_command_works_at_the_first_step(client, admin):
    await client.say("/feedback")
    await client.say("/cancel")
    assert "Действие отменено" in client.last[0]
    await client.say("текст после отмены")  # уже не отзыв
    assert sent_to(client, admin) == []


async def test_second_click_does_not_send_the_feedback_twice(client, admin):
    await send(client, "один раз")
    await client.press("feedback:named")  # повторное нажатие
    assert len(sent_to(client, admin)) == 1


async def test_two_simultaneous_clicks_send_one_feedback(client, admin):
    # настоящая гонка: оба нажатия обрабатываются одновременно, пока идёт отправка
    await client.say("/feedback")
    await client.say("гонка")
    await asyncio.gather(client.press("feedback:named"), client.press("feedback:named"))
    assert len(sent_to(client, admin)) == 1


async def test_stale_button_sends_nothing(client, admin):
    await client.press("feedback:named")  # состояния отзыва нет
    assert sent_to(client, admin) == []


async def test_text_instead_of_a_button_gives_a_hint(client, admin):
    await client.say("/feedback")
    await client.say("отзыв")
    await client.say("ещё текст")
    assert "Выбери кнопкой" in client.last[0]
    assert sent_to(client, admin) == []


async def test_delivery_failure_is_reported_and_does_not_start_the_cooldown(
    client, admin, clock
):
    client.fake.fail_for.add(admin)  # автор заблокировал бота или id неверный
    await send(client, "не дойдёт")
    assert "Не получилось отправить" in client.last[0]
    assert TG_ID not in feedback.last_sent  # человек может сразу попробовать снова
    client.fake.fail_for.clear()
    await send(client, "теперь дойдёт")
    assert len(sent_to(client, admin)) == 1


async def test_command_works_in_the_middle_of_another_dialog(client, admin, world):
    await client.say("кофе 7")  # бот ждёт выбор категории
    await client.say("/feedback")
    assert "Напиши одним сообщением" in client.last[0]
