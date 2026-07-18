"""Финальный проход по бэклогу UX-критики: мелкие дефекты рендеринга."""

from jinja2 import Environment, meta

from src.models.processing import TranscriptionResult
from src.services.processing.protocol_formatter import ProtocolFormatter
from src.services.template_library import TemplateLibrary
from src.utils.pdf_converter import _format_inline, _is_horizontal_rule, strip_emoji

# ---------------------------------------------------------------------------
# PDF: markdown-линейка не должна печататься текстом «---»
# ---------------------------------------------------------------------------

def test_dashes_line_is_horizontal_rule():
    assert _is_horizontal_rule("---")
    assert _is_horizontal_rule("----------")


def test_bullet_and_text_are_not_rules():
    assert not _is_horizontal_rule("- пункт")
    assert not _is_horizontal_rule("обычный текст")
    assert not _is_horizontal_rule("--")


# ---------------------------------------------------------------------------
# Fallback: пустой meeting_title не оставляет заголовка-сироты «# »
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# «Сроки» не дублируют «📌 Задачи и сроки» в Стандартном
# ---------------------------------------------------------------------------

def test_standard_template_has_no_deadlines_duplicate():
    standard = next(
        t for t in TemplateLibrary().get_all_templates()
        if t["name"] == "Стандартный протокол встречи"
    )
    env = Environment()
    variables = meta.find_undeclared_variables(env.parse(standard["content"]))
    assert "deadlines" not in variables
    assert "## Сроки" not in standard["content"]


# ---------------------------------------------------------------------------
# Инлайн-разметка PDF согласована с чатом
# ---------------------------------------------------------------------------

def test_pdf_bold_converted():
    assert _format_inline("**Дата:** 20 мая") == "<b>Дата:</b> 20 мая"


def test_pdf_single_asterisk_stays_literal():
    # чат не конвертирует одиночные звёздочки — PDF ведёт себя так же
    assert _format_inline("5 * 3 = 15") == "5 * 3 = 15"


def test_pdf_inline_code_gets_mono_font():
    assert _format_inline("`git pull`") == '<font face="Courier">git pull</font>'


# ---------------------------------------------------------------------------
# Эмодзи в контенте PDF: глифов в шрифте нет — снимаем, а не показываем тофу
# ---------------------------------------------------------------------------

def test_content_emoji_stripped_without_double_spaces():
    assert strip_emoji("Решили ✅ запускать") == "Решили запускать"


def test_plain_text_untouched_by_emoji_strip():
    text = "Обычный текст с дефисом - и числом 15"
    assert strip_emoji(text) == text


# ---------------------------------------------------------------------------
# Имя файла протокола — от названия встречи, а не от файла записи
# ---------------------------------------------------------------------------

def test_protocol_file_name_from_meeting_title():
    from src.services.result_sender import _protocol_file_name

    name = _protocol_file_name(
        "# Дейли команды разработки\n\n## ✅ Решения\n- ок", "voice_message_123.mp3"
    )
    assert name == "Дейли команды разработки"


def test_protocol_file_name_sanitized_and_bounded():
    from src.services.result_sender import _protocol_file_name

    name = _protocol_file_name("# Отчёт: год/квартал * «итоги»\n\nтело", "a.mp3")
    assert "/" not in name and "*" not in name and ":" not in name
    assert len(name) <= 60


def test_protocol_file_name_falls_back_to_source_file():
    from src.services.result_sender import _protocol_file_name

    assert _protocol_file_name("без заголовка вовсе", "recording.mp3") == "recording"


def test_enhanced_fallback_empty_title_uses_default():
    formatter = ProtocolFormatter()
    out = formatter._format_enhanced_fallback(
        {
            "meeting_title": "",
            "discussion": "Достаточно длинное обсуждение деталей запуска, "
            "чтобы fallback не свалился в базовую транскрипцию. " * 3,
        },
        TranscriptionResult(transcription="текст"),
    )
    assert not out.startswith("# \n")
    assert out.startswith("# Протокол встречи")
