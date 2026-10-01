from decimal import Decimal, InvalidOperation


def parse_amount(text: str):
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
