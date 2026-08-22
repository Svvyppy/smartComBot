from decimal import Decimal, InvalidOperation


def parse_decimal(text: str) -> Decimal:
    normalized = text.strip().replace(" ", "").replace(",", ".")
    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("Введите число, например 18621.4") from exc
    if not value.is_finite():
        raise ValueError("Введите конечное числовое значение")
    return value


def format_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_money(value: Decimal) -> str:
    return f"{value:.2f}"

