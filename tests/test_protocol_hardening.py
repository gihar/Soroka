"""Краевые случаи конвейера протоколов.

Филлеры LLM нормализуются к пустоте, форматтер не сочиняет «Не указано»,
доставка проверяет результат отправки, маппинг типов встреч покрывает
все категории классификатора, PDF-шрифты имеют переносимый фолбэк.
"""

from unittest.mock import AsyncMock

import pytest

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services import result_sender
from src.services.processing.protocol_formatter import ProtocolFormatter
from src.services.smart_template_selector import (
    _CATEGORY_KEYWORDS,
    MEETING_TYPE_TO_CATEGORIES,
)
from src.services.template_library import TemplateLibrary

_TEMPLATE = {
    "content": (
        "# {{ meeting_title or 'Протокол встречи' }}\n"
        "{% if decisions %}\n## ✅ Решения\n{{ decisions }}\n{% endif %}\n"
        "{% if discussion %}\n## 💬 Обсуждение\n{{ discussion }}\n{% endif %}"
    )
}


def _transcription() -> TranscriptionResult:
    return TranscriptionResult(transcription="полный текст транскрипции встречи")


# ---------------------------------------------------------------------------
# Нормализация филлеров перед рендерингом шаблона
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filler", ["Не указано", "не указано.", "N/A", "—", "-"])
def test_filler_section_hidden(filler):
    formatter = ProtocolFormatter()
    llm_result = {
        "meeting_title": "Планёрка команды разработки",
        "decisions": filler,
        "discussion": "Обсудили детали запуска новой подсистемы рендеринга протоколов.",
    }
    out = formatter.format_protocol(_TEMPLATE, llm_result, _transcription())
    assert "Решения" not in out
    assert "Не указано" not in out
    assert "Обсудили детали" in out


def test_real_content_not_normalized():
    formatter = ProtocolFormatter()
    llm_result = {
        "meeting_title": "Планёрка команды разработки",
        "decisions": "- Запускаем подсистему рендеринга в понедельник",
        "discussion": "Коротко сверили статусы по задачам и рискам запуска.",
    }
    out = formatter.format_protocol(_TEMPLATE, llm_result, _transcription())
    assert "Запускаем подсистему" in out


# ---------------------------------------------------------------------------
# Форматтер не сочиняет заглушки
# ---------------------------------------------------------------------------

def test_task_without_assignee_omits_placeholder():
    formatter = ProtocolFormatter()
    assert formatter.format_dict_to_text({"item": "Сделать отчёт"}) == "- Сделать отчёт"


def test_empty_dict_and_list_render_empty():
    formatter = ProtocolFormatter()
    assert formatter.format_dict_to_text({}) == ""
    assert formatter.format_list_to_text([]) == ""


def test_json_item_without_due_omits_placeholder():
    formatter = ProtocolFormatter()
    out = formatter.fix_json_in_text('{"item": "Отчёт", "assignee": "Иван"}')
    assert "Не указано" not in out
    assert "Отчёт" in out


# ---------------------------------------------------------------------------
# Доставка: результат отправки проверяется
# ---------------------------------------------------------------------------

def _request() -> ProcessingRequest:
    return ProcessingRequest(file_name="meeting.mp3", llm_provider="openai", user_id=1)


def _result() -> ProcessingResult:
    body = "\n".join(f"- пункт {i} с достаточно длинным текстом строки" for i in range(300))
    return ProcessingResult(
        transcription_result=_transcription(),
        protocol_text=f"# Протокол\n\n## 💬 Обсуждение\n{body}",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )


def _fake_user_service(monkeypatch, mode: str) -> None:
    import src.services.user_service as user_service_module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            class User:
                protocol_output_mode = mode

            return User()

    monkeypatch.setattr(user_service_module, "UserService", FakeUserService)


@pytest.mark.asyncio
async def test_lost_message_part_returns_delivery_failure(monkeypatch):
    calls = {"n": 0}

    async def flaky_send(bot, chat_id, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 3 else object()  # третья отправка — flood

    monkeypatch.setattr(result_sender, "safe_send_message", flaky_send)
    _fake_user_service(monkeypatch, "messages")

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result()
    )
    assert ok is False


@pytest.mark.asyncio
async def test_lost_document_returns_delivery_failure(monkeypatch):
    async def ok_send(bot, chat_id, **kwargs):
        return object()

    async def lost_document(bot, chat_id, **kwargs):
        return None

    monkeypatch.setattr(result_sender, "safe_send_message", ok_send)
    monkeypatch.setattr(result_sender, "safe_send_document", lost_document)
    _fake_user_service(monkeypatch, "file")

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result()
    )
    assert ok is False


# ---------------------------------------------------------------------------
# Маппинг типов встреч
# ---------------------------------------------------------------------------

def test_all_classifier_categories_have_template_mapping():
    for category in _CATEGORY_KEYWORDS:
        assert category in MEETING_TYPE_TO_CATEGORIES, category


def test_every_category_boost_reaches_some_system_template():
    templates = TemplateLibrary().get_all_templates()
    texts = [
        f"{t['name']} {t.get('description', '')}".lower() for t in templates
    ]
    for category, keywords in MEETING_TYPE_TO_CATEGORIES.items():
        assert any(
            keyword in text for keyword in keywords for text in texts
        ), f"{category}: ни один ключ не матчится ни с одним шаблоном"


def test_daily_template_reachable_by_status_boost():
    daily = next(
        t for t in TemplateLibrary().get_all_templates() if t["name"] == "Дейли"
    )
    text = f"{daily['name']} {daily.get('description', '')}".lower()
    assert any(kw in text for kw in MEETING_TYPE_TO_CATEGORIES["status"])


# ---------------------------------------------------------------------------
# PDF: переносимый фолбэк шрифтов
# ---------------------------------------------------------------------------

def test_font_candidates_include_existing_cyrillic_font():
    import os

    from src.utils.pdf_converter import _font_candidates

    assert any(os.path.exists(path) for path in _font_candidates())
