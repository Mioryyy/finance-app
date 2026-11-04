from datetime import date
from decimal import Decimal

import pytest

from app.parsing import (
    extract_date,
    looks_like_emoji,
    parse_amount,
    parse_date,
    parse_day_month,
    parse_entry,
    parse_upcoming_date,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("50", Decimal("50.00")),
        ("50,5", Decimal("50.50")),
        ("0.01", Decimal("0.01")),
        ("99999999.99", Decimal("99999999.99")),
    ],
)
def test_parse(value, expected):
    assert parse_amount(value) == expected


@pytest.mark.parametrize(
    "value",
    [("nan"), ("inf"), ("-100"), ("0"), ("0.004"), ("1e30"), ("-1e30"), ("abc"), ("")],
)
def test_parse_invalid(value):
    assert parse_amount(value) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("кофе 5", ("кофе", Decimal("5.00"), "expense")),
        ("такси до дома 12,5", ("такси до дома", Decimal("12.50"), "expense")),
        ("+500 зарплата", ("зарплата", Decimal("500.00"), "income")),
        ("зарплата +500", ("зарплата", Decimal("500.00"), "income")),
        ("+100", ("", Decimal("100.00"), "income")),
        ("50", ("", Decimal("50.00"), "expense")),
    ],
)
def test_parse_entry(text, expected):
    assert parse_entry(text) == expected


@pytest.mark.parametrize(
    "text", [None, "", "   ", "кофе", "кофе -5", "+ 500 зарплата", "+abc", "+"]
)
def test_parse_entry_invalid(text):
    assert parse_entry(text) is None


@pytest.mark.parametrize("text", ["🍔", "👍", "👨‍👩‍👧", "❤️", " 🎮 "])
def test_looks_like_emoji(text):
    assert looks_like_emoji(text)


@pytest.mark.parametrize(
    "text", [None, "", "привет", "a", "1", "🍔 еда", "🍔🍔🍔🍔🍔🍔🍔🍔🍔"]
)
def test_not_emoji(text):
    assert not looks_like_emoji(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("5 кофе", ("кофе", Decimal("5.00"), "expense")),
        ("12,5 такси до дома", ("такси до дома", Decimal("12.50"), "expense")),
        ("кофе 2 5", ("кофе 2", Decimal("5.00"), "expense")),
    ],
)
def test_parse_entry_amount_first(text, expected):
    assert parse_entry(text) == expected


TODAY = date(2026, 11, 4)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("вчера кофе 5", ("кофе 5", date(2026, 11, 3))),
        ("кофе 5 вчера", ("кофе 5", date(2026, 11, 3))),
        ("Позавчера 5 кофе", ("5 кофе", date(2026, 11, 2))),
        ("кофе 5 сегодня", ("кофе 5", TODAY)),
        ("кофе 5 01.11", ("кофе 5", date(2026, 11, 1))),
        ("кофе 5 01.11.2026", ("кофе 5", date(2026, 11, 1))),
        ("кофе 5 31.12", ("кофе 5", date(2025, 12, 31))),
        ("+500 стипендия вчера", ("+500 стипендия", date(2026, 11, 3))),
    ],
)
def test_extract_date(text, expected):
    assert extract_date(text, TODAY) == expected


@pytest.mark.parametrize("text", ["кофе 5", "такси 12.5", "такси 10.10", "вчера", None])
def test_extract_date_not_a_date(text):
    assert extract_date(text, TODAY) == (text, None)


def test_tomorrow_is_a_date_word():
    assert parse_date("завтра", TODAY) == date(2026, 11, 5)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("завтра", date(2026, 11, 5)),
        ("сегодня", TODAY),
        ("05.11", date(2026, 11, 5)),
        ("03.11", date(2027, 11, 3)),  # в этом году уже прошло: следующий
        ("04.11", TODAY),
        ("15.12", date(2026, 12, 15)),
        ("15.12.2026", date(2026, 12, 15)),
        ("29.02", None),  # ближайшие 2026 и 2027 невисокосные
    ],
)
def test_parse_upcoming_date(text, expected):
    assert parse_upcoming_date(text, TODAY) == expected


@pytest.mark.parametrize("text", ["пятница", "32.01", "", "1.13"])
def test_parse_upcoming_date_invalid(text):
    assert parse_upcoming_date(text, TODAY) is None


@pytest.mark.parametrize(
    "text, expected",
    [("05.11", (5, 11)), (" 5.1 ", (5, 1)), ("29.02", (29, 2))],
)
def test_parse_day_month(text, expected):
    assert parse_day_month(text) == expected


@pytest.mark.parametrize("text", ["30.02", "05.11.2026", "вчера", "13.13", ""])
def test_parse_day_month_invalid(text):
    assert parse_day_month(text) is None
