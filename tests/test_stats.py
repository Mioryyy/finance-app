from datetime import date
from decimal import Decimal

from app.bot.handlers.stats import resolve_period, stats_text

TODAY = date(2026, 11, 10)  # вторник


def test_current_month_compares_same_days_of_previous():
    title, start, end, prev_start, prev_end, label = resolve_period(None, TODAY)
    assert title == "Ноябрь 2026"
    assert (start, end) == (date(2026, 11, 1), TODAY)
    assert (prev_start, prev_end) == (date(2026, 10, 1), date(2026, 10, 10))
    assert label == "прошлый месяц"


def test_finished_month_compares_with_whole_previous_month():
    _, start, end, prev_start, prev_end, _ = resolve_period("03.2026", TODAY)
    assert (start, end) == (date(2026, 3, 1), date(2026, 3, 31))
    assert (prev_start, prev_end) == (date(2026, 2, 1), date(2026, 2, 28))


def test_week_and_today():
    _, start, end, prev_start, prev_end, _ = resolve_period("неделя", TODAY)
    assert (start, end) == (date(2026, 11, 9), TODAY)
    assert (prev_start, prev_end) == (date(2026, 11, 2), date(2026, 11, 3))
    _, start, end, prev_start, prev_end, label = resolve_period("Сегодня", TODAY)
    assert start == end == TODAY
    assert prev_start == prev_end == date(2026, 11, 9)


def test_unknown_period():
    assert resolve_period("когда-нибудь", TODAY) is None


def test_stats_text_percent_and_trend():
    expenses = [
        ("BYN", "🍔 Еда", Decimal("75"), 3),
        ("BYN", "🚌 Транспорт", Decimal("25"), 2),
    ]
    incomes = [("BYN", "💰 Зарплата", Decimal("300"), 1)]
    prev = [("BYN", "🍔 Еда", Decimal("50"), 2)]
    text = stats_text("Ноябрь 2026", "прошлый месяц", expenses, incomes, prev)
    assert "🍔 Еда: 75 Br · 75%" in text
    assert "🚌 Транспорт: 25 Br · 25%" in text
    assert "Итого расходов: 100 Br" in text
    assert "на 100% больше" in text
    assert "Разница: +200 Br" in text


def test_stats_text_currencies_are_not_mixed_and_html_is_escaped():
    expenses = [
        ("BYN", "<b>Еда", Decimal("10"), 1),
        ("USD", "Еда", Decimal("5"), 1),
    ]
    text = stats_text("Ноябрь 2026", "прошлый месяц", expenses, [], [])
    assert "<b>BYN</b>" in text and "<b>USD</b>" in text
    assert "&lt;b&gt;Еда: 10 Br" in text
    assert "трат не было" in text
