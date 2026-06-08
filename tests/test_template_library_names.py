"""Шаблоны в коде должны иметь русские имена."""
from src.services.template_library import TemplateLibrary


def test_no_english_template_names():
    names = {t["name"] for t in TemplateLibrary().get_all_templates()}
    assert "Daily Standup" not in names
    assert "Sprint Retrospective" not in names
    assert "Дейли" in names
    assert "Ретроспектива спринта" in names


def test_template_content_headers_russified():
    by_name = {t["name"]: t["content"] for t in TemplateLibrary().get_all_templates()}
    assert "# Daily Standup" not in by_name["Дейли"]
    assert by_name["Дейли"].lstrip().startswith("# Дейли")
    assert "# Sprint Retrospective" not in by_name["Ретроспектива спринта"]
    assert "# Ретроспектива спринта" in by_name["Ретроспектива спринта"]
