"""Утилиты шаблонов для отображения: сортировка и имя."""
from typing import Any, List, Optional


def sort_templates_by_name(templates: List) -> List:
    """Вернуть новый список шаблонов, отсортированный по имени (регистронезависимо).

    Не мутирует вход. Сортировка строго по алфавиту, без приоритета is_default.
    """
    return sorted(templates, key=lambda t: t.name.casefold())


def template_name_of(template: Any, default: Optional[str] = None) -> Optional[str]:
    """Имя шаблона устойчиво: объект (атрибут ``name``) или dict (ключ ``"name"``).

    Единственная точка этого паттерна — раньше он дублировался в трёх местах
    (выбор бриф-контракта, предупреждение форматтера, перегенерация).
    """
    return (
        getattr(template, "name", None)
        or (template.get("name") if isinstance(template, dict) else None)
        or default
    )
