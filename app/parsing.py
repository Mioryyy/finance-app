import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation


def parse_amount(text: str | None):
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    if not 0 < amount <= Decimal("99999999.99"):
        return None
    amount = amount.quantize(Decimal("0.01"))
    if amount > 0:
        return amount
    return None


def looks_like_emoji(text: str | None) -> bool:
    # без букв и цифр и коротко: 👍, 🍔, 👨‍👩‍👧 подходят, «привет» — нет
    if not text or len(text.strip()) > 8:
        return False
    return not any(ch.isalnum() or ch.isspace() for ch in text.strip())


def parse_entry(text: str | None):
    # «кофе 5» и «5 кофе» — расход; «+500 зарплата» или «зарплата +500» — доход
    if not text:
        return None
    parts = text.split()
    if not parts:
        return None
    if len(parts[0]) > 1 and parts[0].startswith("+"):
        raw_amount, name_parts, tx_type = parts[0][1:], parts[1:], "income"
    else:
        *name_parts, raw_amount = parts
        tx_type = "expense"
        if raw_amount.startswith("+"):
            raw_amount, tx_type = raw_amount[1:], "income"
        if parse_amount(raw_amount) is None and len(parts) > 1:
            # в конце суммы нет: пробуем начало («5 кофе»)
            raw_amount, name_parts = parts[0], parts[1:]
    amount = parse_amount(raw_amount)
    if amount is None:
        return None
    return " ".join(name_parts), amount, tx_type


DATE_WORDS = {"завтра": -1, "сегодня": 0, "вчера": 1, "позавчера": 2}
DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?$")


def parse_date(token: str, today: date | None = None) -> date | None:
    # «вчера», «05.11» или «05.11.2026»; None, если это не дата.
    # Будущую дату тоже возвращаем: решает вызывающий
    today = today or date.today()  # noqa: DTZ011
    token = token.strip().lower()
    if token in DATE_WORDS:
        return today - timedelta(days=DATE_WORDS[token])
    match = DATE_RE.match(token)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        if year is None:
            result = date(today.year, int(month), int(day))
            if result > today:
                # «31.12» в январе — это прошлый год
                result = date(today.year - 1, int(month), int(day))
            return result
        year = int(year) + 2000 if len(year) == 2 else int(year)
        return date(year, int(month), int(day))
    except ValueError:
        return None


def extract_date(text: str | None, today: date | None = None):
    """Достать дату из записи: «вчера кофе 5» -> («кофе 5», вчера).

    Токен считается датой, только если без него остаётся нормальная запись:
    так «такси 12.5» остаётся суммой, а не 12 мая.
    """
    if not text:
        return text, None
    parts = text.split()
    for index, token in enumerate(parts):
        found = parse_date(token, today)
        if found is None:
            continue
        rest = " ".join(parts[:index] + parts[index + 1 :])
        if parse_entry(rest) is not None:
            return rest, found
    return text, None


def parse_upcoming_date(token: str, today: date | None = None) -> date | None:
    """Ближайшая дата не раньше сегодня: «завтра», «05.11», «05.11.2026».

    В отличие от parse_date «05.11» без года здесь значит ближайшее 5 ноября
    (в этом году, если оно ещё не прошло, иначе в следующем). Дата с явным
    годом или слово «вчера» может оказаться в прошлом: решает вызывающий.
    """
    today = today or date.today()  # noqa: DTZ011
    match = DATE_RE.match(token.strip().lower())
    if match and match.group(3) is None:
        day, month = int(match.group(1)), int(match.group(2))
        for year in (today.year, today.year + 1):
            try:
                result = date(year, month, day)
            except ValueError:
                return None
            if result >= today:
                return result
        return None
    return parse_date(token, today)


def parse_day_month(text: str) -> tuple[int, int] | None:
    # «05.11» -> (5, 11) для событий раз в год; 29.02 допустим (високосный год)
    match = DATE_RE.match(text.strip())
    if not match or match.group(3) is not None:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    try:
        date(2024, month, day)  # високосный год: 29.02 существует
    except ValueError:
        return None
    return day, month


def parse_period_month(text: str):
    # «09.2026» -> первое число месяца; None, если формат другой
    try:
        return datetime.strptime(text, "%m.%Y").date()  # noqa: DTZ007
    except ValueError:
        return None
