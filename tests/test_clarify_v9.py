"""Критика v9, clarify: ясные тексты — ошибки со следующим шагом и единый словарь.

Инварианты бьют по РЕАЛЬНЫМ генераторам (карточка, подпись фрагмента,
MessageBuilder, кадр ошибки прогресса) и по исходникам хендлеров там, где текст
живёт в замыкании. Бренд PRODUCT.md — «нейтральный, надёжный, лаконичный»;
эталон голоса ошибки — result_sender: одно простое предложение + следующий шаг.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

_SRC = Path(__file__).resolve().parent.parent / "src"


def _source(rel: str) -> str:
    return (_SRC / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Карточка сопоставления: анонимная метка показывается как «Спикер N»
# ---------------------------------------------------------------------------


def test_humanize_speaker_label_maps_to_speaker():
    """«SPEAKER_1» → «Спикер 1»; ключ данных остаётся нетронутым."""
    from src.ux.speaker_label import humanize_speaker_label

    assert humanize_speaker_label("SPEAKER_1") == "Спикер 1"
    assert humanize_speaker_label("SPEAKER_12") == "Спикер 12"
    # Метка не по шаблону возвращается как есть (страховка).
    assert humanize_speaker_label("Иван") == "Иван"


def test_card_rows_render_speaker_label_humanized():
    """Строки карточки показывают «Спикер N», а не «SPEAKER_N» (HTML и plain)."""
    from src.ux.card_content import MappingCard, SpeakerRow

    card = MappingCard(
        header="Проверьте сопоставление спикеров",
        rows=(
            SpeakerRow(speaker_id="SPEAKER_1", display_name="Иван"),
            SpeakerRow(speaker_id="SPEAKER_2", display_name=None),
        ),
    )
    for rendered in (card.to_html(), card.to_plain()):
        assert "Спикер 1" in rendered
        assert "Спикер 2" in rendered
        assert "SPEAKER_1" not in rendered
        assert "SPEAKER_2" not in rendered


def test_subview_header_names_speaker_humanized():
    """Заголовок под-вида называет спикера по-русски, без «SPEAKER_» и без ✏."""
    from src.ux.speaker_mapping_ui import _card_header

    header = _card_header(participants=[], current_editing_speaker="SPEAKER_2")
    assert "Спикер 2" in header
    assert "SPEAKER_2" not in header
    assert "✏" not in header


def test_voice_caption_humanizes_speaker_label():
    """Подпись фрагмента записи — «🔊 Спикер N», без сырого «SPEAKER_N»."""
    from src.ux.speaker_audio_preview import _build_caption

    caption = _build_caption("SPEAKER_1", speakers_text=None)
    assert caption == "🔊 Спикер 1"
    assert "SPEAKER_1" not in caption


# ---------------------------------------------------------------------------
# Карточка: кнопки — ❌ только для ошибок, ✏ снят, ⏭ для пропуска, ⬅️ назад
# ---------------------------------------------------------------------------

# Лексикон и типографика Фазы 1 (базовые кодпоинты, без VS-16).
_LEXICON = {"✅", "❌", "⚠", "⏳", "\U0001f4c4", "⬅", "⏭", "❓", "\U0001f50a", "⚙"}
_TYPOGRAPHY = set("—–…•→✓·")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002300-\U000023FF\U00002600-\U000027BF"
    "\U00002190-\U000021FF\U00002460-\U000025FF\U00002B00-\U00002BFF]"
)


def _emojis(text: str) -> list[str]:
    stripped = text.replace("️", "")
    return [c for c in _EMOJI_RE.findall(stripped) if c not in _TYPOGRAPHY]


def _two_speaker_diarization():
    from src.models.diarization import Diarization, Segment

    return Diarization(segments=[
        Segment(speaker="SPEAKER_1", text="Первый"),
        Segment(speaker="SPEAKER_2", text="Второй"),
    ])


def _card_keyboard(current_editing_speaker=None):
    from src.ux.speaker_mapping_ui import create_mapping_keyboard

    diarization = _two_speaker_diarization()
    return create_mapping_keyboard(
        speaker_mapping={"SPEAKER_1": "Иван"},
        diarization=diarization,
        participants=[{"name": "Иван"}],
        user_id=42,
        current_editing_speaker=current_editing_speaker,
    )


def _labels(keyboard) -> list[str]:
    return [btn.text for row in keyboard.inline_keyboard for btn in row]


def test_card_action_buttons_do_not_use_error_cross():
    """«Оставить без имени» и «Пропустить сопоставление» — без ❌ (он для ошибок)."""
    main = _labels(_card_keyboard())
    sub = _labels(_card_keyboard(current_editing_speaker="SPEAKER_2"))

    skip = next(t for t in main if "ропустить" in t)
    keep = next(t for t in sub if "ставить без имени" in t)
    assert "❌" not in skip
    assert "❌" not in keep
    assert skip.strip().startswith("⏭")  # ⏭ для «пропустить» разрешён


def test_card_buttons_carry_only_lexicon_glyphs():
    """Все подписи карточки несут только лексикон Фазы 1: ✏ снят, ◀ → ⬅️."""
    for keyboard in (_card_keyboard(), _card_keyboard(current_editing_speaker="SPEAKER_2")):
        for label in _labels(keyboard):
            for glyph in _emojis(label):
                assert glyph in _LEXICON, f"глиф вне лексикона: {glyph!r} в {label!r}"
            assert "✏" not in label


def test_card_speaker_buttons_show_human_label():
    """Кнопки спикеров показывают «Спикер N», не «SPEAKER_N»."""
    labels = _labels(_card_keyboard())
    assert any("Спикер 2" in t for t in labels)
    assert all("SPEAKER_" not in t for t in labels)


def test_skip_confirm_keyboard_has_no_pencil():
    """Под-вид подтверждения пропуска: «Назвать спикеров» без ✏."""
    from src.ux.speaker_mapping_ui import create_skip_confirm_keyboard

    labels = _labels(create_skip_confirm_keyboard(user_id=42))
    naming = next(t for t in labels if "азвать" in t)
    assert "✏" not in naming


# ---------------------------------------------------------------------------
# Карточка: вводная строка «зачем шаг» и сохранённое предупреждение «Участник N»
# ---------------------------------------------------------------------------


def _build_card(current_editing_speaker=None):
    from src.ux.speaker_mapping_ui import build_mapping_card

    diarization = _two_speaker_diarization()
    return build_mapping_card(
        speaker_mapping={},
        diarization=diarization,
        participants=[],
        current_editing_speaker=current_editing_speaker,
    )


def test_main_view_card_has_intro_line():
    """Главный вид несёт одну вводную строку: зачем называть спикеров."""
    card = _build_card()
    rendered = card.to_plain()
    assert "кто есть кто" in rendered
    assert "номеров спикеров" in rendered


def test_subview_card_has_no_intro_line():
    """Под-вид (уже называешь одного) вводную строку не повторяет."""
    card = _build_card(current_editing_speaker="SPEAKER_1")
    assert "кто есть кто" not in card.to_plain()


def test_card_keeps_participant_n_warning():
    """Предупреждение про «Участник N» на месте — вводная его не вытеснила."""
    assert "Участник N" in _build_card().to_plain()


# ---------------------------------------------------------------------------
# MessageBuilder: голос ошибки вместо канцелярит-формуляра «Тип:/Детали:»
# ---------------------------------------------------------------------------


def test_error_message_drops_formulaire_and_keeps_next_step():
    """Нет «Тип:/Детали:/Произошла ошибка»; есть ❌ и следующий шаг."""
    from src.ux.message_builder import MessageBuilder

    text = MessageBuilder.error_message("network", details="ConnectionError at 0x7f")
    assert "**Тип:**" not in text
    assert "Детали:" not in text
    assert "Произошла ошибка" not in text
    assert "ConnectionError" not in text  # техническая деталь — только в логи
    assert text.startswith("❌")
    # Следующий шаг: минимум две строки (что не получилось + как восстановиться).
    assert len([ln for ln in text.splitlines() if ln.strip()]) >= 2


def test_error_message_unknown_type_is_honest_general():
    """Незнакомый тип — честный общий текст со следующим шагом, не заглушка кода."""
    from src.ux.message_builder import MessageBuilder

    text = MessageBuilder.error_message("whatever_internal_code")
    assert "whatever_internal_code" not in text
    assert "Попробуйте" in text or "попробуйте" in text


def test_file_too_big_has_no_contradiction_and_uses_mb():
    """«Файл слишком большой»: без «система сжимает», ≤3 варианта, единица «МБ»."""
    from src.ux.message_builder import MessageBuilder

    text = MessageBuilder.file_validation_error(
        {"type": "size", "actual_size": 30 * 1024 * 1024, "max_size": 20}
    )
    assert "автоматически сжимает" not in text  # противоречие с самой ошибкой снято
    assert " МБ" in text and " MB" not in text
    bullets = [ln for ln in text.splitlines() if ln.strip().startswith("•")]
    assert 1 <= len(bullets) <= 3


# ---------------------------------------------------------------------------
# Прогресс: кадр ошибки не показывает сырой текст исключения
# ---------------------------------------------------------------------------


async def test_progress_error_frame_hides_raw_exception(monkeypatch):
    """Сырой exception-текст не доезжает до пользователя; есть следующий шаг.

    Шаг с 30.07.2026 зависит от причины: здесь таймаут сети, и честный совет —
    подождать, а не слать запись заново. Универсальное «отправьте ещё раз»
    осталось только для неопознанных сбоев (см. test_failure_voice).
    """
    from src.ux import progress_tracker as pt

    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text
        return message

    monkeypatch.setattr(pt, "safe_edit_text", fake_edit)

    tracker = pt.ProgressTracker(MagicMock(), 1, MagicMock())
    tracker.setup_default_stages()
    await tracker.error(
        "transcription", "Timeout after 30s: HTTPSConnectionPool(host='api')"
    )

    text = captured.get("text", "")
    assert "Timeout after 30s" not in text
    assert "HTTPSConnectionPool" not in text
    assert "❌" in text
    assert "через несколько минут" in text


async def test_progress_error_frame_step_matches_cause(monkeypatch):
    """Перегрузка сервера не выдаётся за проблему файла (прод 30.07.2026)."""
    from src.ux import progress_tracker as pt

    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text
        return message

    monkeypatch.setattr(pt, "safe_edit_text", fake_edit)

    tracker = pt.ProgressTracker(MagicMock(), 1, MagicMock())
    tracker.setup_default_stages()
    await tracker.error(
        "transcription",
        "Ошибка при транскрипции",
        "Файл не может быть обработан: Высокое использование памяти: 91.1% >= 90.0%",
    )

    text = captured.get("text", "")
    assert "91.1%" not in text
    assert "обычно повторная попытка помогает" not in text
    assert "нашей стороне" in text


# ---------------------------------------------------------------------------
# Единая терминология: словарь один во всех пользовательских строках
# ---------------------------------------------------------------------------

# Хендлеры, где текст ошибок и меню живёт в замыканиях — сканируем исходник.
_USER_FACING = [
    "handlers/message_handlers.py",
    "handlers/command_handlers.py",
    "handlers/participants_handlers.py",
    "handlers/callbacks/processing_callbacks.py",
    "handlers/callbacks/settings_callbacks.py",
    "handlers/callbacks/speaker_mapping_callbacks.py",
    "ux/quick_actions.py",
    "ux/feedback_system.py",
    "ux/message_builder.py",
]


def test_no_llm_provider_term_in_user_strings():
    """«LLM провайдер» — историческое имя; пользователь видит «модель»."""
    for rel in _USER_FACING:
        assert "LLM провайдер" not in _source(rel), rel


def test_no_latin_mb_unit_in_user_strings():
    """Размеры пишем «МБ», не «MB»."""
    for rel in ("ux/quick_actions.py", "ux/message_builder.py"):
        assert "MB" not in _source(rel), rel


def test_ai_model_term_unified_to_russian():
    """«AI модели» приведены к «модели ИИ» — латиница-название снято."""
    for rel in ("ux/quick_actions.py", "handlers/callbacks/settings_callbacks.py"):
        assert "AI модел" not in _source(rel), rel


def test_output_format_labels_unified():
    """Форматы вывода: «В сообщение» и «В файл PDF/Word/Markdown» единообразно."""
    src = _source("handlers/callbacks/settings_callbacks.py")
    assert "В файл Markdown" in src
    assert "В файл PDF" in src
    assert "В файл md" not in src
    assert "В файл pdf" not in src


def test_single_feedback_slogan_everywhere():
    """Слоган фидбека один и без восклицания: «Помогите сделать бота лучше»."""
    from src.ux.feedback_system import FeedbackUI

    prompt = FeedbackUI.feedback_intro_text()
    assert "Помогите сделать бота лучше" in prompt
    assert "!" not in prompt
    for rel in ("handlers/command_handlers.py", "ux/quick_actions.py"):
        assert "Помогите нам" not in _source(rel), rel


# ---------------------------------------------------------------------------
# Ошибки-тупики: в основном потоке нет голого «❌ Произошла ошибка»
# ---------------------------------------------------------------------------


def test_no_bare_dead_end_errors_in_primary_flow():
    """Голое «Произошла ошибка» вычищено из файлов основного потока."""
    primary = [
        "handlers/message_handlers.py",
        "handlers/command_handlers.py",
        "handlers/participants_handlers.py",
        "handlers/callbacks/processing_callbacks.py",
        "handlers/callbacks/speaker_mapping_callbacks.py",
        "ux/quick_actions.py",
    ]
    for rel in primary:
        assert "Произошла ошибка" not in _source(rel), rel


def test_no_llm_provider_reset_message_leaks():
    """Сообщение о потерянном состоянии не поминает «LLM провайдер»."""
    src = _source("handlers/message_handlers.py")
    assert "не выбран LLM" not in src
