from decimal import Decimal

import pytest

from app.parsing import looks_like_emoji, parse_amount, parse_entry


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
