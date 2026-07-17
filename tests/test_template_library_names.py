"""Шаблоны в коде должны иметь русские имена и русские заголовки."""
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
    assert "# Sprint Retrospective" not in by_name["Ретроспектива спринта"]
    # шапка — название встречи с русским фолбэком на имя шаблона
    assert "'Дейли'" in by_name["Дейли"].splitlines()[0]
    assert "'Ретроспектива спринта'" in by_name["Ретроспектива спринта"].splitlines()[0]
