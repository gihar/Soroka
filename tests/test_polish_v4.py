"""Критика v4, polish: последовательные метки секций, PDF-списки, тихий feedback."""

import inspect

from src.services.template_library import TemplateLibrary

# Сквозные секции несут навигационную метку из единого словаря;
# спец-секции типа встречи — осознанно без меток.
_SHARED_SECTION_LABELS = {
    "Повестка дня": "📋",
    "Структура лекции": "📋",
    "Ключевые выводы": "💡",
    "Открытые вопросы": "❓",
    "Вопросы и ответы": "❓",
}


def test_shared_sections_carry_labels():
    for template in TemplateLibrary().get_all_templates():
        content = template["content"]
        for line in content.splitlines():
            if not line.startswith("## "):
                continue
            heading = line[3:].strip()
            for name, emoji in _SHARED_SECTION_LABELS.items():
                if heading.endswith(name):
                    assert heading == f"{emoji} {name}", (
                        f"{template['name']}: «{heading}» без метки {emoji}"
                    )


def test_core_labels_unchanged():
    standard = next(
        t for t in TemplateLibrary().get_all_templates()
        if t["name"] == "Стандартный протокол встречи"
    )
    for heading in ("## ✅ Решения", "## 📌 Задачи и сроки",
                    "## ⚠️ Блокеры и риски", "## 💬 Обсуждение",
                    "## 📅 Следующие шаги"):
        assert heading in standard["content"]


# ---------------------------------------------------------------------------
# PDF: нумерованные списки с отступом, как маркированные
# ---------------------------------------------------------------------------

def test_pdf_numbered_lists_have_own_style():
    from src.utils import pdf_converter

    src_text = inspect.getsource(pdf_converter)
    assert "NumberItem" in src_text
    assert "styles['NumberItem']" in src_text


# ---------------------------------------------------------------------------
# Feedback: нейтральный тон по PRODUCT.md
# ---------------------------------------------------------------------------

def test_feedback_tone_is_quiet():
    import src.ux.feedback_system as fs

    src_text = inspect.getsource(fs)
    for loud in (
        "поможет улучшить качество работы бота!",
        "Рады, что вам понравилось",
        "Мы стараемся стать лучше",
        "🎉",
        "😔",
        "🙏",
    ):
        assert loud not in src_text, loud


def test_feedback_still_points_to_command():
    import src.ux.feedback_system as fs

    assert "/feedback" in inspect.getsource(fs)
