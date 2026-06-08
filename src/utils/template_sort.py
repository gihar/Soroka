"""Алфавитная сортировка шаблонов для отображения в UI."""
from typing import List


def sort_templates_by_name(templates: List) -> List:
    """Вернуть новый список шаблонов, отсортированный по имени (регистронезависимо).

    Не мутирует вход. Сортировка строго по алфавиту, без приоритета is_default.
    """
    return sorted(templates, key=lambda t: t.name.casefold())
