"""Утилиты шаблонов для отображения: сортировка, имя, подпись категории."""
from typing import Any, List, Optional

# Единственный словарь подписей категорий на все меню шаблонов.
# Ключи — реально существующие категории системных шаблонов (см. TemplateLibrary)
# плюс синтетическая «all». Мёртвых product/sales здесь нет намеренно.
CATEGORY_LABELS = {
    "general": "📋 Общие",
    "technical": "⚙️ Технические",
    "management": "👔 Управленческие",
    "educational": "🎓 Образовательные",
    "all": "📝 Все шаблоны",
}


def category_label(category: str) -> str:
    """Подпись категории для кнопок и заголовков — одна на все меню.

    Неизвестная категория показывается как есть, без смены регистра: прежний
    ``.title()`` в фолбэке превращал «educational» в англицизм «Educational».
    """
    return CATEGORY_LABELS.get(category, f"📁 {category}")


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
