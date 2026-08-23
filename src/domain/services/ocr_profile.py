from decimal import Decimal


def mechanical_value(digits: str, fraction_digits: int) -> Decimal:
    if not digits or not digits.isdigit():
        raise ValueError("mechanical digits must contain only decimal digits")
    if not 0 <= fraction_digits <= 6:
        raise ValueError("fraction digits must be between 0 and 6")
    if fraction_digits == 0:
        return Decimal(digits)
    integer = digits[:-fraction_digits] or "0"
    fraction = digits[-fraction_digits:]
    return Decimal(f"{integer}.{fraction}")


def infer_mechanical_fraction_digits(
    digits: str | None,
    corrected_value: Decimal,
) -> int | None:
    if digits is None or not digits.isdigit():
        return None
    for fraction_digits in range(0, min(6, len(digits)) + 1):
        if mechanical_value(digits, fraction_digits) == corrected_value:
            return fraction_digits
    return None
