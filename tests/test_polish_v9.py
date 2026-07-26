"""Полировка (критика v9, Фаза 4): админ-поверхность в общем каноне.

Инварианты Фаз 1–3 (лексикон эмодзи, единая HTML-разметка, единый источник
текста) распространяются на административную поверхность — крупнейшего
оффендера репозитория. Бьём по РЕАЛЬНЫМ генераторам: клавиатуре меню админа,
чистым билдерам админ-вью и по собранным сообщениям, а также проверяем, что
мёртвые хелперы удалены (модуль их больше не экспортирует).
"""

import re
from pathlib import Path
from types import SimpleNamespace

_SRC = Path(__file__).resolve().parent.parent / "src"


def _source(rel: str) -> str:
    return (_SRC / rel).read_text(encoding="utf-8")

# Разрешённый лексикон Фаз 1–3 (базовые кодпоинты без VS-16), один глиф = одно
# значение. Тот же набор, что в test_quiet_messages_v9 / test_clarify_v9.
LEXICON = {"✅", "❌", "⚠", "⏳", "\U0001f4c4", "⬅", "⏭", "❓", "\U0001f50a", "⚙"}
_TYPOGRAPHY = set("—–…•→✓·")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002300-\U000023FF\U00002600-\U000027BF"
    "\U00002190-\U000021FF\U00002460-\U000025FF\U00002B00-\U00002BFF]"
)


def _strip_vs(text: str) -> str:
    return text.replace("️", "")


def emojis(text: str) -> list[str]:
    return [c for c in _EMOJI_RE.findall(_strip_vs(text)) if c not in _TYPOGRAPHY]


def assert_only_lexicon(text: str) -> None:
    for glyph in emojis(text):
        assert glyph in LEXICON, f"глиф вне лексикона: {glyph!r} в {text!r}"


def assert_at_most_one_emoji_per_line(text: str) -> None:
    for line in text.splitlines():
        found = emojis(line)
        assert len(found) <= 1, f"более одного эмодзи в строке: {line!r} -> {found}"


def _button_texts(markup) -> list[str]:
    rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", [])
    return [btn.text for row in rows for btn in row]


# ---------------------------------------------------------------------------
# Клавиатура меню администратора: только лексиконные глифы
# ---------------------------------------------------------------------------


def test_admin_menu_keyboard_carries_only_lexicon():
    """Кнопки меню админа несут только лексикон (📊🏥📈🧹📥 сняты)."""
    from src.ux.quick_actions import QuickActionsUI

    for label in _button_texts(QuickActionsUI.create_admin_menu()):
        assert_only_lexicon(label)


def test_admin_entry_button_single_source_and_no_forbidden_glyph():
    """Вход в меню админа — один источник (константа), без 🔧 (⚙ занят настройками)."""
    from src.handlers import message_handlers
    from src.ux.quick_actions import ADMIN_MENU_BUTTON

    assert_only_lexicon(ADMIN_MENU_BUTTON)
    assert "🔧" not in ADMIN_MENU_BUTTON
    # Фильтр текст-хендлера мёню зеркалит ту же константу (нет дрейфа подписи).
    assert ADMIN_MENU_BUTTON in message_handlers._menu_button_texts()


# ---------------------------------------------------------------------------
# Чистые билдеры админ-вью: единый источник текста, HTML, лексикон
# ---------------------------------------------------------------------------

# Заметные декоративные глифы прежней админки — не должны возвращаться.
_ADMIN_FORBIDDEN = set("🔧📊📈🧹📥🏥🎙📝💾🧠⚡📁📂🗂🗑♻🤖📋🔒👥⭐▶⛔☁🏠🎯🎤🐆🔄🔍")


def _assert_html_canon(text: str) -> None:
    """Единый канон поверхности: HTML вместо `**`, только лексиконные глифы."""
    assert "**" not in text, f"осталась `**`-разметка: {text!r}"
    for glyph in _strip_vs(text):
        assert glyph not in _ADMIN_FORBIDDEN, f"декоративный глиф {glyph!r} в {text!r}"
    assert_only_lexicon(text)
    assert_at_most_one_emoji_per_line(text)


def test_admin_help_text_is_html_and_lexicon():
    """Справка админа: HTML-теги, команды в <code>, без 🔧 и `**`."""
    from src.ux.admin_views import admin_help_text

    text = admin_help_text()
    _assert_html_canon(text)
    assert "<b>Административные команды</b>" in text
    assert "<code>/status</code>" in text


def test_performance_report_is_html_lexicon_and_uses_mb_ru():
    """Отчёт производительности: HTML, без сек-эмодзи, единица «МБ» не «MB»."""
    from src.ux.admin_views import performance_report

    text = performance_report(
        cache_stats={"hit_rate_percent": 90, "memory_usage_mb": 12,
                     "memory_usage_percent": 30, "memory_entries": 5, "disk_entries": 2},
        memory_stats={"current_memory": {"percent": 40, "process_mb": 55.0},
                      "is_optimizing": False},
        task_stats={"active_tasks": 1, "max_concurrent": 4, "success_rate": 99.0},
        metrics_stats={"processing": {"requests_1h": 3, "success_rate_percent": 100,
                                      "avg_duration_seconds": 12, "avg_efficiency_ratio": 1.0}},
    )
    _assert_html_canon(text)
    assert "<b>Статистика производительности</b>" in text
    assert " МБ" in text and "MB" not in text


def test_cleanup_stats_report_is_html_lexicon_mb_and_words_for_toggle():
    """Статистика файлов: HTML, «МБ», автоочистка словом (не ❌ — он для ошибок)."""
    from src.ux.admin_views import cleanup_stats_report

    stats = {"temp_files": 3, "temp_size_mb": 1.5, "cache_files": 2, "cache_size_mb": 0.5,
             "old_temp_files": 1, "old_cache_files": 0}
    on = cleanup_stats_report(stats, interval_minutes=30, temp_max_age_hours=6,
                              cache_max_age_hours=24, cleanup_enabled=True)
    off = cleanup_stats_report(stats, interval_minutes=30, temp_max_age_hours=6,
                               cache_max_age_hours=24, cleanup_enabled=False)
    for text in (on, off):
        _assert_html_canon(text)
        assert " МБ" in text and "MB" not in text
    assert "включена" in on
    assert "выключена" in off
    assert "❌" not in off  # выключено — не ошибка


def test_cleanup_done_report_is_html_and_keeps_success_stamp():
    """Результат очистки: единый ✅-штамп успеха, HTML, без 🗑/📊."""
    from src.ux.admin_views import cleanup_done_report

    text = cleanup_done_report(
        cleaned_count=7,
        stats={"temp_files": 0, "temp_size_mb": 0.0, "cache_files": 0, "cache_size_mb": 0.0},
    )
    _assert_html_canon(text)
    assert text.startswith("✅")
    assert "Удалено файлов: 7" in text


def test_health_report_maps_status_to_lexicon_glyphs():
    """Проверка здоровья: healthy→✅, degraded→⚠, unhealthy→❌, unknown→❓; без 🏥."""
    from src.ux.admin_views import health_report

    results = {
        "db": SimpleNamespace(status=SimpleNamespace(value="healthy"),
                              message="ок", response_time=0.012),
        "llm": SimpleNamespace(status=SimpleNamespace(value="unhealthy"),
                               message="нет ответа", response_time=None),
    }
    text = health_report(results)
    _assert_html_canon(text)
    assert "<b>Проверка здоровья</b>" in text
    assert "✅" in text and "❌" in text


def test_transcription_mode_view_is_html_and_marks_active_with_check():
    """Режим транскрипции: HTML-текст, кнопки без 🏠☁️🐆, активная помечена ✅."""
    from src.ux.admin_views import transcription_mode_view

    text, keyboard = transcription_mode_view("cloud")
    _assert_html_canon(text)
    assert "<b>Режим транскрипции</b>" in text
    labels = _button_texts(keyboard)
    for label in labels:
        assert_only_lexicon(label)
    active = next(l for l in labels if l.startswith("✅"))
    assert "Облачная" in active


# ---------------------------------------------------------------------------
# Поверхностный инвариант всей админки: HTML-канон, без `**`, MB и декора
# ---------------------------------------------------------------------------


def test_admin_surface_source_is_html_canon():
    """admin_handlers и admin_views: без `**`-разметки, латинского MB и декор-глифов."""
    for rel in ("handlers/admin_handlers.py", "ux/admin_views.py"):
        src = _source(rel)
        assert "**" not in src, f"осталась `**`-разметка в {rel}"
        assert "MB" not in src, f"латинское «MB» вместо «МБ» в {rel}"
        for glyph in _strip_vs(src):
            assert glyph not in _ADMIN_FORBIDDEN, f"декоративный глиф {glyph!r} в {rel}"


def test_admin_markdown_limited_to_status_report():
    """parse_mode=\"Markdown\" в админке — только для отчёта monitoring (2 отправки).

    Отчёт monitoring_api.format_status_report() — канонический Markdown чужого
    модуля; он рендерится в HTML на границе rate-limiter. Остальная поверхность
    админки — прямой Telegram HTML.
    """
    src = _source("handlers/admin_handlers.py")
    assert src.count('parse_mode="Markdown"') == 2
