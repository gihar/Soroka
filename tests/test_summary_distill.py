"""Сводное сообщение: 3–4 строки на HTML, тех-детали — только в логи.

Сводка лежит прямо над протоколом и пересылается вместе с ним — model-id,
количество символов и процент сжатия там не место (критика v2, P1 №4).
"""

from unittest.mock import AsyncMock

import pytest

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services import result_sender
from src.ux.message_builder import MessageBuilder


def _result_dict(**overrides) -> dict:
    base = {
        "template_used": {"name": "Дейли"},
        "llm_provider_used": "openai",
        "llm_model_name": "gpt-5-mini",
        "transcription_result": {
            "transcription": "т" * 84000,
            "diarization": None,
            "compression_info": {"compressed": True, "compression_ratio": 37.0},
        },
        "processing_duration": 128.4,
        "speaker_mapping": {"SPEAKER_00": "Анна", "SPEAKER_01": "Пётр"},
    }
    base.update(overrides)
    return base


def test_summary_is_short():
    message = MessageBuilder.processing_complete_message(_result_dict())
    assert len(message.splitlines()) <= 4
    assert len(message) < 300


def test_summary_has_no_tech_details():
    message = MessageBuilder.processing_complete_message(_result_dict())
    assert "ИИ" not in message
    assert "gpt-5-mini" not in message
    assert "символов" not in message
    assert "Сжатие" not in message


def test_summary_core_facts_present():
    message = MessageBuilder.processing_complete_message(_result_dict())
    assert "Протокол готов" in message
    assert "Дейли" in message
    assert "2" in message  # сопоставлено участников
    assert "2 мин 8 с" in message  # время в читаемом формате


def test_summary_is_valid_telegram_html():
    message = MessageBuilder.processing_complete_message(
        _result_dict(template_used={"name": "Мой <шаблон> & Ко"})
    )
    assert "**" not in message  # legacy-разметки больше нет
    assert "Мой &lt;шаблон&gt; &amp; Ко" in message
    assert message.count("<b>") == message.count("</b>")


def test_summary_omits_missing_facts():
    message = MessageBuilder.processing_complete_message(
        _result_dict(processing_duration=None, speaker_mapping=None)
    )
    assert "⏱" not in message
    assert "👥" not in message


@pytest.mark.asyncio
async def test_summary_sent_as_html(monkeypatch):
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

    req = ProcessingRequest(file_name="meeting.mp3", llm_provider="openai", user_id=1)
    res = ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text="# Протокол\n\n## ✅ Решения\n- ок",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )
    ok = await result_sender.send_result_to_user(AsyncMock(), 1, 1, req, res)

    assert ok is True
    assert sent[0]["parse_mode"] == "HTML"
