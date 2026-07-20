"""Единый словарь подписей категорий шаблонов.

Три меню (управление шаблонами, быстрый выбор, /templates) раньше держали
собственные словари подписей — они расходились, а фолбэк `f'📁 {cat.title()}'`
давал англицизм «📁 Educational». Теперь подпись одна на всех: `category_label`.
"""

import inspect
import os
import sys

# Хендлеры делают `from services import ...` — им нужен src на пути.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from src.utils.template_sort import category_label  # noqa: E402


def test_known_categories_have_house_labels():
    assert category_label("general") == "📋 Общие"
    assert category_label("technical") == "⚙️ Технические"
    assert category_label("management") == "👔 Управленческие"
    assert category_label("educational") == "🎓 Образовательные"


def test_all_category_label():
    assert category_label("all") == "📝 Все шаблоны"


def test_unknown_category_keeps_original_case():
    # Прежний .title() превращал бы «educational» в англицизм «Educational».
    assert category_label("educational_beta") == "📁 educational_beta"
    assert category_label("прочее") == "📁 прочее"


def test_handlers_use_shared_label_not_local_dicts():
    """Ни один хендлер не рендерит англицизм и не держит мёртвых категорий."""
    import src.handlers.callbacks.template_mgmt_callbacks as mgmt
    import src.handlers.command_handlers as cmd

    for module in (mgmt, cmd):
        src_text = inspect.getsource(module)
        assert "category_label" in src_text, f"{module.__name__} не использует category_label"
        # Мёртвые категории (product/sales) и англицизм-фолбэк выкинуты.
        assert "Educational" not in src_text
        assert "🚀 Продуктовые" not in src_text
        assert "💼 Продажи" not in src_text
        assert ".title()" not in src_text
