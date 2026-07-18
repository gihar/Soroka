"""Краевые случаи итерации critique v2: доступность ОД, честные деградации, сплиттер.

Снапшот: .impeccable/critique/2026-07-18T09-38-05Z__src-services-template-library-py.md
"""

from unittest.mock import AsyncMock

import pytest
from jinja2 import Environment, meta

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services import result_sender
from src.services.processing.protocol_formatter import ProtocolFormatter
from src.services.protocol_render import render_protocol_messages
from src.services.smart_template_selector import (
    _CATEGORY_KEYWORDS,
    MEETING_TYPE_TO_CATEGORIES,
    SmartTemplateSelector,
)
from src.services.template_library import TemplateLibrary


def _od_template() -> dict:
    return next(
        t for t in TemplateLibrary().get_all_templates()
        if t["name"] == "Протокол ОД (Поручения)"
    )


def _render(content: str, **values: str) -> str:
    env = Environment()
    variables = meta.find_undeclared_variables(env.parse(content))
    data = {var: values.get(var, "") for var in variables}
    return env.from_string(content).render(**data)


# ---------------------------------------------------------------------------
# «Протокол ОД» доступен пользователю
# ---------------------------------------------------------------------------

def test_od_template_is_visible_system_template():
    """is_default=True → шаблон виден в списке выбора (created_by=? OR is_default=1)."""
    assert _od_template()["is_default"] is True


def test_management_category_exists_in_classifier():
    assert "management" in _CATEGORY_KEYWORDS


def test_management_meeting_is_classified():
    selector = SmartTemplateSelector()
    transcription = (
        "Фиксируем поручения по итогам совещания. Первое поручение: подготовить "
        "отчёт, ответственный Иванов, срок пятнадцатое августа. Второе поручение: "
        "проверить исполнение, ответственный Петров, срок конец месяца. "
        "Контроль исполнения поручений за директором."
    )
    top_category, _scores = selector._score_categories(transcription)
    assert top_category == "management"


def test_every_boost_category_is_reachable_by_classifier():
    """Обратная проверка: ключ маппинга без категории классификатора — мёртвый boost."""
    for category in MEETING_TYPE_TO_CATEGORIES:
        assert category in _CATEGORY_KEYWORDS, category


# ---------------------------------------------------------------------------
# Пустой ОД не уходит молча
# ---------------------------------------------------------------------------

def test_empty_od_states_no_tasks_recorded():
    rendered = _render(_od_template()["content"], meeting_title="Совещание у директора")
    assert "Поручений в записи не зафиксировано" in rendered


def test_od_with_tasks_has_no_empty_notice():
    rendered = _render(
        _od_template()["content"],
        meeting_title="Совещание",
        tasks_od="1. Отчёт. Отв. Иванов. Срок — 20.08.2026",
    )
    assert "не зафиксировано" not in rendered
    assert "## 📌 Поручения" in rendered


# ---------------------------------------------------------------------------
# Честный fallback: транскрипция не маскируется под протокол
# ---------------------------------------------------------------------------

def _transcription() -> TranscriptionResult:
    return TranscriptionResult(transcription="полный текст расшифровки встречи")


def _request() -> ProcessingRequest:
    return ProcessingRequest(file_name="meeting.mp3", llm_provider="openai", user_id=1)


def _result() -> ProcessingResult:
    return ProcessingResult(
        transcription_result=_transcription(),
        protocol_text="# Протокол\n\n## ✅ Решения\n- ок",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )


def test_empty_llm_result_fallback_warns_user():
    formatter = ProtocolFormatter()
    out = formatter.format_protocol({"content": "# {{ meeting_title }}"}, "", _transcription())
    assert "⚠️" in out
    assert "расшифровк" in out.lower()
    assert "полный текст расшифровки" in out


def test_last_resort_fallback_warns_user():
    formatter = ProtocolFormatter()
    # dict со слишком короткими значениями: рендер и enhanced fallback не проходят пороги
    out = formatter.format_protocol({"content": "# {{ meeting_title }}"}, {"x": "y"}, _transcription())
    assert "⚠️" in out


# ---------------------------------------------------------------------------
# Сплиттер: балансировка тегов и нумерация частей
# ---------------------------------------------------------------------------

def test_hard_wrapped_bold_line_keeps_tags_balanced():
    words = " ".join(f"**слово{i}** обычное{i}" for i in range(400))
    md = f"# Протокол\n\n## 💬 Обсуждение\n{words}"
    parts = render_protocol_messages(md, max_length=1000)
    assert len(parts) > 1
    for part in parts:
        assert part.count("<b>") == part.count("</b>"), part[:120]
        assert len(part) <= 1000


@pytest.mark.asyncio
async def test_multipart_messages_are_numbered(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs["text"])
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)

    body = "\n".join(f"- пункт {i} с достаточно длинным содержимым строки" for i in range(300))
    ok = await result_sender._send_protocol_as_messages(
        AsyncMock(), 1, f"# Протокол\n\n## 💬 Обсуждение\n{body}"
    )

    assert ok is True
    assert len(sent) > 1
    for i, text in enumerate(sent, start=1):
        assert text.startswith(f"<i>Часть {i}/{len(sent)}</i>\n")
        assert len(text) <= result_sender.MAX_MESSAGE_LENGTH


@pytest.mark.asyncio
async def test_single_message_has_no_part_prefix(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs["text"])
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)

    ok = await result_sender._send_protocol_as_messages(AsyncMock(), 1, "# Дейли\n\n- ок")
    assert ok is True
    assert len(sent) == 1
    assert "Часть" not in sent[0]


# ---------------------------------------------------------------------------
# Доставка PDF без deprecated tempfile.mktemp
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pdf_mode_delivers_document(monkeypatch):
    documents = []

    async def fake_send_message(bot, chat_id, **kwargs):
        return object()

    async def fake_send_document(bot, chat_id, **kwargs):
        documents.append(kwargs)
        return object()

    async def fake_convert(markdown_text, output_path):
        with open(output_path, "wb") as f:
            f.write(b"%PDF-1.4 fake")

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send_message)
    monkeypatch.setattr(result_sender, "safe_send_document", fake_send_document)
    monkeypatch.setattr(
        "src.utils.pdf_converter.convert_markdown_to_pdf_async", fake_convert
    )

    import src.services.user_service as user_service_module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            class User:
                protocol_output_mode = "pdf"

            return User()

    monkeypatch.setattr(user_service_module, "UserService", FakeUserService)

    req = ProcessingRequest(file_name="meeting.mp3", llm_provider="openai", user_id=1)
    res = ProcessingResult(
        transcription_result=_transcription(),
        protocol_text="# Протокол\n\n## ✅ Решения\n- ок",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )
    ok = await result_sender.send_result_to_user(AsyncMock(), 1, 1, req, res)

    assert ok is True
    assert len(documents) == 1


def _fake_user_service(monkeypatch, mode: str) -> None:
    import src.services.user_service as user_service_module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            class User:
                protocol_output_mode = mode

            return User()

    monkeypatch.setattr(user_service_module, "UserService", FakeUserService)


@pytest.mark.asyncio
async def test_pdf_failure_with_vanished_temp_still_falls_back_to_md(monkeypatch):
    """Конвертер упал и не оставил файла — фолбэк на .md обязан выжить."""
    import os

    documents = []

    async def fake_send_message(bot, chat_id, **kwargs):
        return object()

    async def fake_send_document(bot, chat_id, **kwargs):
        documents.append(kwargs)
        return object()

    async def exploding_convert(markdown_text, output_path):
        os.remove(output_path)  # конвертер прибрал за собой перед падением
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send_message)
    monkeypatch.setattr(result_sender, "safe_send_document", fake_send_document)
    monkeypatch.setattr(
        "src.utils.pdf_converter.convert_markdown_to_pdf_async", exploding_convert
    )
    _fake_user_service(monkeypatch, "pdf")

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result()
    )

    assert ok is True
    assert len(documents) == 1
    assert documents[0]["document"].filename.endswith(".md")


def test_no_deprecated_mktemp_in_result_sender():
    import inspect

    assert "mktemp" not in inspect.getsource(result_sender)


# ---------------------------------------------------------------------------
# Расширение словаря филлеров
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filler", ["неизвестно", "Не определено", "нет", "Отсутствуют"])
def test_extended_fillers_normalized(filler):
    from src.services.processing.protocol_formatter import _normalize_filler

    assert _normalize_filler(filler) == ""


def test_meaningful_short_values_kept():
    from src.services.processing.protocol_formatter import _normalize_filler

    assert _normalize_filler("нет блокеров, всё в порядке") != ""
    assert _normalize_filler("15.08.2026") != ""


# ---------------------------------------------------------------------------
# Мёртвый код удалён
# ---------------------------------------------------------------------------

def test_dead_speaker_mapping_message_removed():
    assert not hasattr(ProtocolFormatter, "format_speaker_mapping_message")
