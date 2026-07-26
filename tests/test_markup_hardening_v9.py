"""Единая HTML-разметка поверхности сообщений (критика v9, ADR-0005).

Инварианты бьют по РЕАЛЬНЫМ отправкам: замыкания-хендлеры зовём через роутер с
подставным Message и перехватываем текст и parse_mode; статические билдеры зовём
напрямую. Проверяем: (а) четыре бага «литеральные звёздочки» ушли, (б) на
собранной поверхности нет `**`-разметки, (в) отправки несут parse_mode="HTML",
(г) динамика (имя шаблона/участника) экранируется, (д) русское склонение.
"""

import ast
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _invoke_message_handler(router, name, message):
    """Найти зарегистрированный message-хендлер по имени и вызвать его."""
    for obj in router.message.handlers:
        if obj.callback.__name__ == name:
            return obj.callback(message)
    raise AssertionError(f"хендлер {name} не найден в роутере")


def _mock_message(user_id: int = 999):
    """Подставной Message: .answer перехватывает текст и parse_mode."""
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = user_id
    message.answer = AsyncMock(return_value=MagicMock())
    return message


def _last_answer(message):
    """(text, parse_mode) последней отправки через message.answer."""
    assert message.answer.await_count >= 1, "хендлер не отправил сообщение"
    args, kwargs = message.answer.await_args
    text = kwargs.get("text", args[0] if args else "")
    return text, kwargs.get("parse_mode")


# ---------------------------------------------------------------------------
# Баг 1: кнопка «⚙️ Настройки» — литеральные **звёздочки** без parse_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_button_renders_bold_not_literal_stars():
    """«Настройки бота» приходят жирным <b>, а не буквальными `**`."""
    from src.ux.quick_actions import setup_quick_actions_handlers

    router = setup_quick_actions_handlers()
    message = _mock_message()
    await _invoke_message_handler(router, "settings_button_handler", message)

    text, parse_mode = _last_answer(message)
    assert parse_mode == "HTML"
    assert "**" not in text
    assert "<b>Настройки бота</b>" in text


@pytest.mark.asyncio
async def test_upload_file_button_renders_bold_not_literal_stars():
    """«Загрузка файла» приходит жирным <b>, а не буквальными `**` (баг 2)."""
    from src.ux.quick_actions import setup_quick_actions_handlers

    router = setup_quick_actions_handlers()
    message = _mock_message()
    await _invoke_message_handler(router, "upload_file_button_handler", message)

    text, parse_mode = _last_answer(message)
    assert parse_mode == "HTML"
    assert "**" not in text
    assert "<b>Загрузка файла</b>" in text


@pytest.mark.asyncio
async def test_feedback_skip_renders_bold_not_literal_stars():
    """«Оценка пропущена» (safe_edit_text без parse_mode — баг) уходит в HTML."""
    from src.ux import feedback_system as fs

    captured = {}

    async def fake_edit(message, text, **kwargs):
        captured["text"] = text
        captured["parse_mode"] = kwargs.get("parse_mode")
        return message

    router = fs.setup_feedback_handlers(fs.FeedbackCollector())
    # найдём хендлер пропуска оценки
    handler = next(
        obj.callback for obj in router.callback_query.handlers
        if obj.callback.__name__ == "handle_skip_feedback"
    )
    callback = MagicMock()
    callback.message = MagicMock()
    callback.data = "feedback_skip_protocol_quality"
    import src.utils.telegram_safe as ts
    orig = ts.safe_edit_text
    fs.safe_edit_text = fake_edit  # модульный алиас, по которому зовёт хендлер
    try:
        await handler(callback)
    finally:
        fs.safe_edit_text = orig

    assert captured["parse_mode"] == "HTML"
    assert "**" not in captured["text"]
    assert "<b>Оценка пропущена</b>" in captured["text"]


# ---------------------------------------------------------------------------
# Экранирование канона: только «&», «<», «>» (звёздочки/подчёркивания — текст)
# ---------------------------------------------------------------------------


def test_esc_escapes_only_html_specials():
    """esc экранирует &,<,> и НЕ трогает *, _, ` — под HTML это обычный текст."""
    from src.ux.html_text import esc

    assert esc("A<b>&") == "A&lt;b&gt;&amp;"
    # Звёздочки и подчёркивания в HTML не разметка — остаются как есть.
    assert esc("**жирный** _кур_ `код`") == "**жирный** _кур_ `код`"
    assert esc(None) == ""
    assert esc(42) == "42"


# ---------------------------------------------------------------------------
# Реальные данные: имя шаблона с <,>,&,**,эмодзи — текст, не разметка/поломка
# ---------------------------------------------------------------------------


async def _run_template_preview(name: str, content: str = "# {{ meeting_title }}\nПривет"):
    """Собрать превью шаблона реальным билдером, вернуть отправленный текст."""
    import src.handlers.template_handlers as th

    captured = {}

    async def fake_answer(message, text, **kwargs):
        captured["text"] = text
        captured["parse_mode"] = kwargs.get("parse_mode")
        return message

    template_service = MagicMock()
    template_service.render_template = MagicMock(return_value="Отрендерено")

    orig = th.safe_answer
    th.safe_answer = fake_answer
    try:
        await th._show_template_preview(
            MagicMock(),
            {"template_name": name, "template_content": content},
            template_service,
        )
    finally:
        th.safe_answer = orig
    return captured


@pytest.mark.asyncio
async def test_template_preview_escapes_dangerous_name():
    """Имя шаблона «A<b>&**» рендерится как текст: HTML-спецсимволы экранированы."""
    captured = await _run_template_preview("A<b>&** 🎯")

    text = captured["text"]
    assert captured["parse_mode"] == "HTML"
    # Опасные символы имени экранированы, сырой тег не просочился.
    assert "A&lt;b&gt;&amp;" in text
    assert "<b>&**" not in text
    # Эмодзи остаётся как есть.
    assert "🎯" in text


@pytest.mark.asyncio
async def test_template_preview_long_name_does_not_crash():
    """Имя из 150+ символов не роняет сборку превью."""
    long_name = "Ш" * 180
    captured = await _run_template_preview(long_name)
    assert long_name in captured["text"]


@pytest.mark.asyncio
async def test_template_name_saved_escapes_name():
    """Подтверждение «Название сохранено: <b>…</b>» экранирует ввод пользователя."""
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    import src.handlers.template_handlers as th

    captured = {}

    async def fake_answer(message, text, **kwargs):
        captured["text"] = text
        captured["parse_mode"] = kwargs.get("parse_mode")
        return message

    router = th.setup_template_handlers(MagicMock())
    handler = next(
        obj.callback for obj in router.message.handlers
        if obj.callback.__name__ == "template_name_handler"
    )
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=1, user_id=1),
    )
    message = MagicMock()
    message.text = "Отчёт <b>&"
    message.answer = AsyncMock()
    orig = th.safe_answer
    th.safe_answer = fake_answer
    try:
        await handler(message, state)
    finally:
        th.safe_answer = orig

    assert captured["parse_mode"] == "HTML"
    assert "Отчёт &lt;b&gt;&amp;" in captured["text"]
    assert "<b>Отчёт <b>&" not in captured["text"]


# ---------------------------------------------------------------------------
# Русское склонение счётчика очереди: 1 задача / 2 задачи / 5 задач
# ---------------------------------------------------------------------------


def test_tasks_word_russian_plural():
    from src.ux.queue_tracker import QueuePositionTracker

    word = QueuePositionTracker._tasks_word
    assert word(1) == "задача"
    assert word(2) == "задачи"
    assert word(3) == "задачи"
    assert word(4) == "задачи"
    assert word(5) == "задач"
    assert word(11) == "задач"
    assert word(21) == "задача"
    assert word(22) == "задачи"
    assert word(25) == "задач"
    assert word(111) == "задач"


def test_queue_message_uses_correct_plural():
    from unittest.mock import MagicMock

    from src.ux.queue_tracker import QueuePositionTracker

    tracker = QueuePositionTracker(MagicMock(), 1, "t")
    assert "1 задача" in tracker._format_queue_message(1, 3)
    assert "2 задачи" in tracker._format_queue_message(2, 3)
    assert "5 задач" in tracker._format_queue_message(5, 7)


# ---------------------------------------------------------------------------
# Мелкие эдж-кейсы: рейтинг компактными цифрами; ⏭ единой формой (без VS16)
# ---------------------------------------------------------------------------


def test_rating_keyboard_is_compact_digits_without_stars():
    from src.ux.feedback_system import FeedbackUI

    labels = [
        btn.text
        for row in FeedbackUI.create_rating_keyboard().inline_keyboard
        for btn in row
    ]
    assert "1" in labels and "5" in labels
    assert all("⭐" not in lbl for lbl in labels)


def test_skip_glyph_unified_to_base_codepoint():
    """Кнопки «пропустить» несут ⏭ без VS-16 (U+FE0F) — единая форма."""
    import src.handlers.callbacks.speaker_mapping_callbacks as smc
    from src.ux import speaker_mapping_ui

    for src in (
        __import__("inspect").getsource(speaker_mapping_ui),
        __import__("inspect").getsource(smc),
    ):
        assert "⏭️" not in src, "остался ⏭️ с VS-16 в кнопке/сообщении"


# ---------------------------------------------------------------------------
# Инвариант поверхности: любая отправка с HTML-тегами несёт parse_mode="HTML"
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parent.parent / "src"
_NAME_SENDS = {"safe_answer", "safe_edit_text", "safe_send_message",
               "safe_edit_message", "safe_bot_edit_message"}
_ATTR_SENDS = {"answer", "reply", "send_message", "edit_text", "answer_photo",
               "answer_document", "edit_message_text", "send_document",
               "answer_audio", "edit_caption", "answer_voice"}
_TAG_RE = re.compile(r"</?(b|i|code|pre|u|s)>")


def _surface_files():
    for base in ("ux", "handlers"):
        for path in (_SRC / base).rglob("*.py"):
            if path.name == "admin_handlers.py":
                continue
            yield path


def _call_text(call: ast.Call) -> str:
    parts = []
    nodes = list(call.args) + [kw.value for kw in call.keywords
                               if kw.arg in ("text", "caption", None)]
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                parts.append(sub.value)
    return " ".join(parts)


def test_every_html_tag_send_declares_html_parse_mode():
    """Ни одна отправка поверхности с <b>/<i>/<code>/<pre> не идёт без HTML.

    Ловит регресс, когда `**` заменили на тег, но parse_mode не выставили —
    иначе пользователь увидел бы буквальные теги.
    """
    offenders = []
    for path in _surface_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name not in (_NAME_SENDS | _ATTR_SENDS):
                continue
            if not _TAG_RE.search(_call_text(node)):
                continue
            pm = None
            for kw in node.keywords:
                if kw.arg == "parse_mode" and isinstance(kw.value, ast.Constant):
                    pm = kw.value.value
            if pm != "HTML":
                offenders.append(f"{path.name}:{node.lineno} parse_mode={pm!r}")
    assert not offenders, "HTML-теги без parse_mode=HTML:\n" + "\n".join(offenders)


def test_no_markdown_bold_in_migrated_static_builders():
    """Статические билдеры поверхности не несут `**`-разметку (только HTML).

    Проверяем РЕАЛЬНЫЙ вывод билдеров; `**` внутри <code>/<pre> (документация
    синтаксиса шаблонов) не считается разметкой и вырезается перед проверкой.
    """
    from src.ux.feedback_system import FeedbackUI
    from src.ux.message_builder import MessageBuilder
    from src.ux.queue_tracker import QueuePositionTracker

    tracker = QueuePositionTracker(MagicMock(), 1, "t")
    outputs = [
        MessageBuilder.welcome_message(),
        MessageBuilder.help_message(),
        MessageBuilder.templates_help_message(),
        FeedbackUI.feedback_intro_text(),
        FeedbackUI.format_feedback_request("protocol_quality"),
        tracker._format_queue_message(0, 3),
        tracker._format_queue_message(2, 5),
    ]
    code_pre = re.compile(r"<(code|pre)>.*?</\1>", re.DOTALL)
    for text in outputs:
        stripped = code_pre.sub("", text)
        assert "**" not in stripped, f"осталась `**`-разметка в: {text!r}"
