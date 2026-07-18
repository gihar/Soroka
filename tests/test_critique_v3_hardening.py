"""Бэклог критики v3: порядок сводки, экзотика рендера, PDF-колонтитул."""

import inspect
from unittest.mock import AsyncMock

import pytest

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services import result_sender
from src.utils.pdf_converter import strip_emoji


def _request() -> ProcessingRequest:
    return ProcessingRequest(file_name="meeting.mp3", llm_provider="openai", user_id=1)


def _result(protocol_text: str) -> ProcessingResult:
    return ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text=protocol_text,
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )


def _patch_messages_user(monkeypatch) -> list:
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
    return sent


# ---------------------------------------------------------------------------
# Пустой протокол: без качелей «✅ готов» → «❌ не получился»
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_protocol_sends_no_success_summary(monkeypatch):
    sent = _patch_messages_user(monkeypatch)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result(protocol_text="")
    )

    assert ok is False
    texts = " ".join(kwargs["text"] for kwargs in sent)
    assert "Протокол готов" not in texts


# ---------------------------------------------------------------------------
# Протокол из одних «---» рендерится в ноль сообщений — это не успех
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashes_only_protocol_not_reported_delivered(monkeypatch):
    sent = _patch_messages_user(monkeypatch)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result(protocol_text="---\n\n---")
    )

    assert ok is False
    assert sent  # пользователь получил объяснение, а не тишину


# ---------------------------------------------------------------------------
# PDF: колонтитул без чужого бренда
# ---------------------------------------------------------------------------

def test_pdf_header_has_no_generator_brand():
    from src.utils import pdf_converter

    assert "SOROKA" not in inspect.getsource(pdf_converter)


# ---------------------------------------------------------------------------
# PDF: эмодзи-диапазон покрывает U+2000–25FF, не задевая типографику
# ---------------------------------------------------------------------------

def test_misc_technical_emoji_stripped():
    assert strip_emoji("Решили ⏱ быстро") == "Решили быстро"
    assert strip_emoji("важно ‼ срочно") == "важно срочно"
    assert strip_emoji("шаг ▶ дальше") == "шаг дальше"
    assert strip_emoji("оценка ⭐ пять") == "оценка пять"


def test_typography_survives_emoji_strip():
    text = "Диапазон 5–7, тире — и буллет •, №3, многоточие…"
    assert strip_emoji(text) == text
