import re


def clean_serial_number(serial_number: str) -> str:
    return " ".join(serial_number.upper().split())


def serial_number_keys(serial_number: str) -> frozenset[str]:
    normalized = re.sub(r"[^0-9A-ZА-Я]", "", clean_serial_number(serial_number))
    digits = "".join(character for character in normalized if character.isdigit())
    keys = {normalized} if normalized else set()
    if len(digits) >= 6:
        keys.add(digits)
    return frozenset(keys)


def serial_numbers_match(first: str, second: str) -> bool:
    return bool(serial_number_keys(first) & serial_number_keys(second))
