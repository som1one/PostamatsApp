"""Нормализация телефона для хранения в БД (E.164-подобно: всегда с '+')."""


def normalize_phone_for_storage(phone: str) -> str:
    """
    Убирает пробелы и типичные разделители; если нет ведущего '+', добавляет его.
    Клиент должен передавать номер в международном виде (цифры после '+').
    """
    if not phone or not str(phone).strip():
        raise ValueError("Телефон не указан")

    raw = str(phone).strip().replace("\u00a0", " ")
    compact = "".join(ch for ch in raw if ch not in " \t\n\r-().")

    if not compact:
        raise ValueError("Телефон не указан")

    if not compact.startswith("+"):
        compact = f"+{compact}"

    return compact
