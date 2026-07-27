"""Тихая поверхность сообщений: эмодзи-лексикон и спокойный прогресс (критика v9).

Инварианты сканируют РЕАЛЬНЫЕ генераторы сообщений (не копии строк):
прогресс-экран, очередь, карточку сопоставления и клавиатуры. Бренд PRODUCT.md —
«нейтральный, надёжный, лаконичный»; эмодзи допустимы только как навигационные
метки из фиксированного лексикона, один глиф = одно значение.
"""

import re
from unittest.mock import MagicMock

# Разрешённый лексикон (один глиф = одно значение). Базовые кодпоинты без VS-16.
LEXICON = {"✅", "❌", "⚠", "⏳", "\U0001f4c4",
           "⬅", "⏭", "❓", "\U0001f50a", "⚙"}

# Типографика — не эмодзи: тире, многоточие, буллет, стрелка, галочка, middot.
# ВРЕМЕННО: → и ✓ трактуются как функциональные коннекторы карточки сопоставления
# и исключены из эмодзи-набора до Фазы 2. Фаза 2 разбирает копирайт потока карточки
# и коллизию ✓/✅ (лексиконная галочка успеха) — тогда → и ✓ уйдут из _TYPOGRAPHY.
_TYPOGRAPHY = set("—–…•→✓·")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF"   # пиктографика, эмодзи
    "\U00002300-\U000023FF"    # техсимволы: ⏳ ⏭ ⏱ ⏸
    "\U00002600-\U000027BF"    # разное + дингбаты: ✅ ❌ ✓ ⚙ ⚠ ❓
    "\U00002190-\U000021FF"    # стрелки: → ↩
    "\U00002460-\U000025FF"    # геом. фигуры: ◀ ▶
    "\U00002B00-\U00002BFF]"   # ⬅ ⭐ ⬇
)


def _strip_vs(text: str) -> str:
    """Убрать VS-16 (U+FE0F) — модификатор эмодзи, не отдельный глиф."""
    return text.replace("️", "")


def emojis(text: str) -> list[str]:
    """Эмодзи в строке без типографики (стрелки/галочки/тире — не эмодзи)."""
    return [c for c in _EMOJI_RE.findall(_strip_vs(text)) if c not in _TYPOGRAPHY]


def assert_at_most_one_emoji_per_line(text: str) -> None:
    for line in text.splitlines():
        found = emojis(line)
        assert len(found) <= 1, f"более одного эмодзи в строке: {line!r} -> {found}"


def assert_only_lexicon(text: str) -> None:
    for glyph in emojis(text):
        assert glyph in LEXICON, f"глиф вне лексикона: {glyph!r} в {text!r}"


# ---------------------------------------------------------------------------
# Прогресс-экран: один статусный глиф на строку, без пер-этапных эмодзи и спиннера
# ---------------------------------------------------------------------------


def _tracker():
    from src.ux.progress_tracker import ProgressTracker

    tracker = ProgressTracker(MagicMock(), 1, MagicMock())
    tracker.setup_default_stages()
    return tracker


def _set_states(tracker, completed=(), active=None):
    from datetime import datetime

    for stage_id in completed:
        stage = tracker.stages[stage_id]
        stage.is_completed = True
        stage.started_at = datetime.now()
        stage.completed_at = datetime.now()
    if active:
        tracker.stages[active].is_active = True
        tracker.stages[active].started_at = datetime.now()
        tracker.current_stage = active


def test_progress_active_line_is_single_status_glyph():
    """Активный этап — «⏳ Название», без пер-этапного эмодзи и ASCII-спиннера."""
    tracker = _tracker()
    _set_states(tracker, completed=["preparation"], active="transcription")
    text = tracker._format_progress_text()

    lines = text.splitlines()
    active_line = next(ln for ln in lines if "Транскрипция" in ln)
    done_line = next(ln for ln in lines if "Подготовка" in ln)
    future_line = next(ln for ln in lines if "Анализ" in ln)

    assert active_line.strip().startswith("⏳")  # ⏳ текущий
    assert done_line.strip().startswith("✅")    # ✅ завершённый
    assert not future_line.strip().startswith(("✅", "⏳"))  # будущий — пустой маркер


def test_progress_has_no_per_stage_emoji_or_spinner():
    """Ни 📁🎯🤖, ни 🔄, ни кадров спиннера |/-\\ в любом состоянии экрана."""
    for completed, active in (
        ((), "preparation"),
        (("preparation",), "transcription"),
        (("preparation", "transcription"), "analysis"),
    ):
        t = _tracker()
        _set_states(t, completed=completed, active=active)
        text = t._format_progress_text()
        for glyph in ("\U0001f4c1", "\U0001f3af", "\U0001f916", "\U0001f504"):
            assert glyph not in text, f"{glyph!r} остался в прогрессе"
        for line in text.splitlines():
            stripped = line.rstrip()
            assert not stripped.endswith((" |", " /", " -", " \\")), line
        assert_only_lexicon(text)
        assert_at_most_one_emoji_per_line(text)


def test_progress_final_frame_has_no_second_success_stamp():
    """Финальный кадр не дублирует сводку «✅ Протокол готов» вторым штампом."""
    tracker = _tracker()
    _set_states(tracker, completed=["preparation", "transcription", "analysis"])
    final_text = tracker._format_progress_text(final=True)

    assert "Протокол готов" not in final_text
    assert "Обработка завершена" not in final_text
    assert not final_text.lstrip().startswith("✅")  # без ведущего ✅-штампа
    assert "ниже" not in final_text


# ---------------------------------------------------------------------------
# Очередь: факты без SMM-тона
# ---------------------------------------------------------------------------


def _queue_tracker():
    from src.ux.queue_tracker import QueuePositionTracker

    return QueuePositionTracker(MagicMock(), 1, "task-1")


def test_queue_messages_are_factual_without_smm():
    """Позиция и оценка ожидания — да; «⚡ Скоро начнём», «💡»-советы — нет."""
    tracker = _queue_tracker()
    for position in (0, 1, 2, 5):
        text = tracker._format_queue_message(position, total_in_queue=7)
        for banned in ("Скоро начнем", "Скоро начнём", "очередь скоро",
                       "Вы можете отменить", "⚡", "\U0001f4a1",
                       "\U0001f550", "\U0001f4cd", "\U0001f4ca", "\U0001f504"):
            assert banned not in text, f"{banned!r} в позиции {position}: {text!r}"
        assert_only_lexicon(text)
        assert_at_most_one_emoji_per_line(text)
        assert "очеред" in text.lower()

    long_text = tracker._format_queue_message(5, total_in_queue=7)
    assert "ожидания" in long_text.lower()  # оценка ожидания сохранена


def test_queue_cancel_button_has_no_emoji():
    """Кнопка отмены — «Отменить задачу», без ❌ (❌ только для ошибок)."""
    tracker = _queue_tracker()
    button = tracker.create_cancel_button().inline_keyboard[0][0]
    assert emojis(button.text) == []
    assert "Отменить" in button.text


# ---------------------------------------------------------------------------
# Карточка сопоставления: без 🎭 и без линии-разделителя
# ---------------------------------------------------------------------------


def test_mapping_card_has_no_theater_mask_or_separator():
    """🎭 снят, разделительная линия убрана; функциональные → и ✓ остаются."""
    from src.ux.card_content import MappingCard, SpeakerRow

    card = MappingCard(
        header="Проверьте сопоставление спикеров",
        rows=(SpeakerRow(speaker_id="SPEAKER_1", display_name="Иван"),),
    )
    for rendered in (card.to_html(), card.to_plain()):
        assert "\U0001f3ad" not in rendered  # 🎭
        assert "─" not in rendered       # ────
    # Функциональный коннектор остаётся — это не декоративный эмодзи (→ и ✓
    # временно вне запретного набора до Фазы 2, см. _TYPOGRAPHY выше).
    assert "→" in card.to_plain()        # →


# ---------------------------------------------------------------------------
# Кнопка «Отмена» без эмодзи во всех клавиатурах
# ---------------------------------------------------------------------------


def test_template_picker_cancel_button_has_no_emoji():
    """Пикер шаблонов: кнопка отмены без ✖️/❌/↩️."""
    from src.ux.keyboards import build_template_picker

    keyboard = build_template_picker(
        templates=[], callback_data=lambda t: "x", cancel_callback="cancel_x"
    )
    cancel_btn = keyboard.inline_keyboard[-1][0]
    assert emojis(cancel_btn.text) == []
    assert "Отмена" in cancel_btn.text


# ---------------------------------------------------------------------------
# Широкий инвариант: генераторы сообщений и меню несут только лексикон
# ---------------------------------------------------------------------------

# Явно запрещённые декоративные глифы (критика v9) — не должны встречаться.
FORBIDDEN = set(
    "\U0001f3ad\U0001f680⚡\U0001f4a1\U0001f550\U0001f4cd\U0001f4ca"
    "\U0001f4dd\U0001f4cb\U0001f916\U0001f4c1\U0001f4e4\U0001f4ce\U0001f4ac"
    "\U0001f4be\U0001f527\U0001f3af\U0001f504➕⭐\U0001f3a8\U0001f41b"
    "\U0001f3b5\U0001f3ac\U0001f465\U0001f50d\U0001f4c5\U0001f310\U0001f9f9"
    "\U0001f4c8\U0001f5d1↩✏"
)


def _button_texts(markup) -> list[str]:
    """Подписи всех кнопок клавиатуры (inline или reply)."""
    rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", [])
    return [btn.text for row in rows for btn in row]


def _assert_no_forbidden(text: str) -> None:
    bad = [g for g in _strip_vs(text) if g in FORBIDDEN]
    assert not bad, f"запрещённый глиф {bad} в {text!r}"


def test_message_builder_generators_carry_no_forbidden_glyphs():
    from src.ux.message_builder import MessageBuilder

    result = {
        "template_used": {"name": "Дейли"},
        "processing_duration": 128.0,
        "speaker_mapping": {"SPEAKER_00": "Анна"},
    }
    texts = [
        MessageBuilder.processing_complete_message(result),
        MessageBuilder.error_message("file_size"),
        MessageBuilder.file_validation_error({"type": "size", "actual_size": 3 * 1024**2}),
        MessageBuilder.file_validation_error(
            {"type": "format", "extension": ".xyz",
             "supported_formats": {"audio": ["MP3"], "video": ["MP4"]}}
        ),
        MessageBuilder.templates_help_message(),
    ]
    for text in texts:
        _assert_no_forbidden(text)
    # Сводка сохраняет ЕДИНЫЙ штамп успеха.
    assert MessageBuilder.processing_complete_message(result).startswith("✅")


def test_menus_and_feedback_carry_no_forbidden_glyphs():
    from src.ux.feedback_system import FeedbackUI
    from src.ux.quick_actions import QuickActionsUI

    markups = [
        QuickActionsUI.create_main_menu(123),
        QuickActionsUI.create_settings_menu(is_admin=True),
        QuickActionsUI.create_record_actions_menu()[1],
        FeedbackUI.create_rating_keyboard(),
        FeedbackUI.create_feedback_type_keyboard(),
    ]
    for markup in markups:
        for label in _button_texts(markup):
            _assert_no_forbidden(label)

    # Оценки — простые цифры без ⭐.
    rating_labels = _button_texts(FeedbackUI.create_rating_keyboard())
    assert "1" in rating_labels and "5" in rating_labels
    assert all("⭐" not in lbl for lbl in rating_labels)
