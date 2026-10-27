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
    # «кофе 5» — расход; «+500 зарплата» или «зарплата +500» — доход
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
    amount = parse_amount(raw_amount)
    if amount is None:
        return None
    return " ".join(name_parts), amount, tx_type
