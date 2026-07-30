"""Форматирование дат для читателя протокола (русские названия месяцев)."""

import re
from datetime import datetime

# Родительный падеж: «22 июля 2026», как в живой речи и в поле date протокола.
_RU_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def format_russian_date(moment: datetime) -> str:
    """Дата в русском формате «22 июля 2026» (день без ведущего нуля)."""
    return f"{moment.day} {_RU_MONTHS_GENITIVE[moment.month - 1]} {moment.year}"


def format_russian_day_month(moment: datetime) -> str:
    """День и месяц без года: «22 июля» (для фолбэк-титула протокола)."""
    return f"{moment.day} {_RU_MONTHS_GENITIVE[moment.month - 1]}"


# Числовая дата в любом из привычных разделителей: «27.07.2026», «27/07/2026».
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")


def normalize_russian_date(value: str) -> str:
    """«27.07.2026» → «27 июля 2026»; нераспознанное возвращаем как есть.

    Дата приходит из двух источников с разной формой: извлечение из приглашения
    даёт ``%d.%m.%Y``, ручной ввод — что угодно. В шапке протокола они стоят
    рядом с датой обработки («30 июля 2026»), и разнобой читается как
    небрежность документа, который пересылают «наверх». Выдумывать за
    пользователя нельзя: не похоже на дату — оставляем его формулировку.
    """
    match = _NUMERIC_DATE.match((value or "").strip())
    if not match:
        return value
    day, month, year = (int(part) for part in match.groups())
    try:
        return format_russian_date(datetime(year, month, day))
    except ValueError:
        # «32.13.2026» — не дата; пользователь виднее.
        return value
