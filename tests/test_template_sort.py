"""Тест алфавитной сортировки шаблонов."""
from dataclasses import dataclass

from src.utils.template_sort import sort_templates_by_name


@dataclass
class _T:
    name: str
    is_default: bool = False


def test_sorts_alphabetically_ignoring_is_default():
    items = [
        _T("Техническое совещание", True),
        _T("Груминг бэклога", True),
        _T("Простой шаблон", False),  # не-дефолтный не должен «тонуть» вниз
        _T("Дейли", True),
    ]
    result = [t.name for t in sort_templates_by_name(items)]
    assert result == ["Груминг бэклога", "Дейли", "Простой шаблон", "Техническое совещание"]


def test_casefold_mixed_case():
    items = [_T("яблоко"), _T("Яблоко"), _T("Арбуз")]
    result = [t.name for t in sort_templates_by_name(items)]
    assert result[0] == "Арбуз"  # «А» < «я» по алфавиту, регистр не мешает


def test_returns_new_list_without_mutating_input():
    items = [_T("Б"), _T("А")]
    out = sort_templates_by_name(items)
    assert [t.name for t in items] == ["Б", "А"]  # вход не изменён
    assert [t.name for t in out] == ["А", "Б"]
