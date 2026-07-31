"""Единый формат длительности для всех экранов.

До критики v11 в одном прогоне жили четыре формата, причём два — на одном
экране: «✅ Анализ · 6м 14с» рядом с «Прошло: 380с». Плюс «5 мин 12 с» в сводке
и «~15 мин» в очереди. Формат один: секунды до минуты, минуты с секундами до
часа, дальше часы с минутами.
"""

from typing import Optional


def format_duration(seconds: Optional[float]) -> str:
    """«7 с», «5 мин 12 с», «1 ч 5 мин».

    Округляет до ближайшей секунды (обрезание давало «11 с» для 11.6).
    Бессмысленный вход (None, отрицательное) читается как ноль: величина
    служебная, падать из-за неё экран не должен.
    """
    total = int(round(seconds or 0))
    if total <= 0:
        return "0 с"

    if total < 60:
        return f"{total} с"

    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} мин {secs} с" if secs else f"{minutes} мин"

    hours, rem_minutes = divmod(minutes, 60)
    return f"{hours} ч {rem_minutes} мин" if rem_minutes else f"{hours} ч"
