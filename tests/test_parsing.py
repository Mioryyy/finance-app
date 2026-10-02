from decimal import Decimal

import pytest

from app.parsing import parse_amount


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
