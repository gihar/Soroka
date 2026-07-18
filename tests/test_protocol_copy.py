"""Копирайт конвейера протоколов.

Анти-референсы PRODUCT.md: филлеры («Не указано»), подписи генератора,
сырые исключения в чате, дубли статусных сообщений.
"""

import inspect
from unittest.mock import AsyncMock

import pytest

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.prompts.prompts import FIELD_SPECIFIC_RULES, build_generation_system_prompt
from src.services import result_sender


def _request() -> ProcessingRequest:
    return ProcessingRequest(file_name="meeting.mp3", llm_provider="openai", user_id=1)


def _result(protocol_text: str = "# Протокол\n\n## ✅ Решения\n- ок") -> ProcessingResult:
    return ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text=protocol_text,
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )


# ---------------------------------------------------------------------------
# Промпты: пустые данные -> пустая строка, а не филлер
# ---------------------------------------------------------------------------

def test_system_prompt_requires_empty_string_not_filler():
    prompt = build_generation_system_prompt()
    assert "Не указано" not in prompt
    assert "пуст" in prompt.lower()  # инструкция про пустую строку присутствует


def test_field_rules_do_not_mandate_fillers():
    for name, rule in FIELD_SPECIFIC_RULES.items():
        assert "Не указано" not in rule, name
        assert "не проводил" not in rule, name
        assert "не выявлено" not in rule, name


# ---------------------------------------------------------------------------
# PDF: без подписи генератора
# ---------------------------------------------------------------------------

def test_pdf_has_no_generator_signature():
    from src.utils import pdf_converter

    assert "Сгенерировано" not in inspect.getsource(pdf_converter)


def test_progress_final_does_not_duplicate_summary_promise():
    """«Протокол отправляется ниже» обещает только сводка, не прогресс-трекер."""
    from unittest.mock import MagicMock

    from src.ux.progress_tracker import ProgressTracker

    tracker = ProgressTracker(MagicMock(), 1, MagicMock())
    final_text = tracker._format_progress_text(final=True)
    assert "ниже" not in final_text


# ---------------------------------------------------------------------------
# Доставка: ошибки без сырых исключений, файл без дублирующего статуса
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delivery_error_hides_exception_details(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)

    import src.services.user_service as user_service_module

    class ExplodingUserService:
        async def get_user_by_telegram_id(self, _uid):
            raise RuntimeError("secret_boom_details")

    monkeypatch.setattr(user_service_module, "UserService", ExplodingUserService)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result()
    )

    assert ok is False
    texts = " ".join(kwargs["text"] for kwargs in sent)
    assert "secret_boom_details" not in texts
    assert "ещё раз" in texts  # у пользователя есть следующий шаг


@pytest.mark.asyncio
async def test_empty_protocol_message_offers_next_step(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)

    import src.services.user_service as user_service_module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            class User:
                protocol_output_mode = "messages"

            return User()

    monkeypatch.setattr(user_service_module, "UserService", FakeUserService)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result(protocol_text="")
    )

    assert ok is False
    failure_text = sent[-1]["text"]
    assert "ещё раз" in failure_text


@pytest.mark.asyncio
async def test_file_mode_document_without_duplicate_status_caption(monkeypatch):
    documents = []

    async def fake_send_message(bot, chat_id, **kwargs):
        return object()

    async def fake_send_document(bot, chat_id, **kwargs):
        documents.append(kwargs)
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send_message)
    monkeypatch.setattr(result_sender, "safe_send_document", fake_send_document)

    import src.services.user_service as user_service_module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            class User:
                protocol_output_mode = "file"

            return User()

    monkeypatch.setattr(user_service_module, "UserService", FakeUserService)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result()
    )

    assert ok is True
    assert len(documents) == 1
    # сводка уже сообщила статус; caption не дублирует «Протокол готов!»
    assert documents[0].get("caption") in (None, "")
