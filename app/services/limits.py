"""Лимиты на категории: прогресс и предупреждения после записи траты."""

import html

from app.constants import CURRENCY_SYMBOLS, LIMIT_WARN_PERCENT
from app.repositories.limit_repository import get_limit, month_spent


def limit_icon(spent, limit):
    if spent >= limit:
        return "🔴"
    if spent * 100 >= limit * LIMIT_WARN_PERCENT:
        return "🟡"
    return "🟢"


def limit_line(name, spent, limit, currency):
    # «🟡 🍔 Еда: 85 из 100 Br (85%)»
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    percent = round(spent / limit * 100)
    return (
        f"{limit_icon(spent, limit)} {html.escape(name)}: "
        f"{spent} из {limit} {symbol} ({percent}%)"
    )


def limit_warning_text(name, spent, added, limit, currency):
    """Предупреждение после траты или None, если всё в порядке.

    spent — сумма за месяц уже вместе с только что записанной тратой,
    added — сама трата. Про 80% говорим один раз, в момент пересечения;
    когда лимит уже превышен, напоминаем после каждой траты.
    """
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    before = spent - added
    safe_name = html.escape(name)
    if spent >= limit:
        return f"🔴 Лимит на {safe_name} превышен: {spent} из {limit} {symbol} за месяц"
    crossed = spent * 100 >= limit * LIMIT_WARN_PERCENT > before * 100
    if crossed:
        percent = round(spent / limit * 100)
        return (
            f"🟡 {percent}% лимита на {safe_name}: {spent} из {limit} {symbol} "
            f"за месяц, осталось {limit - spent} {symbol}"
        )
    return None


async def limit_warning(
    session, user_id, category_id, category_name, currency, day, added
):
    # вызывать после flush траты: в сумме за месяц она уже должна быть
    limit = await get_limit(session, user_id, category_id, currency)
    if limit is None:
        return None
    spent = await month_spent(session, user_id, category_id, currency, day)
    return limit_warning_text(category_name, spent, added, limit.amount, currency)
