from decimal import Decimal
from types import SimpleNamespace

from app.bot.handlers.accounts import totals_line


def acc(balance, currency):
    return SimpleNamespace(balance=Decimal(balance), currency=currency)


def test_no_total_for_single_account():
    assert totals_line([acc("10", "BYN")]) is None


def test_total_per_currency():
    accounts = [acc("10.50", "BYN"), acc("4.50", "BYN"), acc("-3", "USD")]
    assert totals_line(accounts) == "💰 Всего: 15.00 Br · -3 $"
