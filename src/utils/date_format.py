"""Форматирование дат для читателя протокола (русские названия месяцев)."""

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
