import re

# Поддерживаемые валюты выбираются явно, чтобы не угадывать точность.
CURRENCIES = {"RUB": 2, "UZS": 2, "USD": 2, "EUR": 2, "KZT": 2, "JPY": 0}
MAX_AMOUNT = 10**12


class ClubError(ValueError):
    pass


def parse_money(value: str, currency: str) -> int:
    precision = CURRENCIES[currency]
    value = value.strip().replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ClubError("Введите сумму числом, например 1000 или 1250,50.")
    whole, _, fraction = value.partition(".")
    if len(fraction) > precision:
        raise ClubError(f"Для {currency} допустимо знаков после запятой: {precision}.")
    amount = int(whole) * 10**precision + int(fraction.ljust(precision, "0") or "0")
    if amount > MAX_AMOUNT:
        raise ClubError("Сумма слишком велика.")
    return amount


def money(amount: int, currency: str) -> str:
    precision = CURRENCIES[currency]
    sign = "−" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), 10**precision)
    result = f"{sign}{whole:,}".replace(",", " ")
    if precision and fraction:
        result += f",{fraction:0{precision}d}"
    return f"{result} {currency}"
