"""Критика v4, craft: действия после доставки протокола.

Протокол доставлен — это не конец разговора: «📄 PDF» и «🔁 Другой шаблон»
работают из сохранённой истории, без повторной отправки записи.
"""

import inspect
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.processing import (  # noqa: E402
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services import result_sender  # noqa: E402


def _request() -> ProcessingRequest:
    return ProcessingRequest(file_name="meeting.mp3", llm_provider="openai", user_id=1)


def _result(history_id=None, protocol_text="# П\n\n## ✅ Решения\n- ок") -> ProcessingResult:
    return ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text=protocol_text,
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
        history_id=history_id,
    )


def _patch_user(monkeypatch, mode="messages"):
    import src.services.user_service as user_service_module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            return SimpleNamespace(protocol_output_mode=mode)

    monkeypatch.setattr(user_service_module, "UserService", FakeUserService)


def _keyboard_datas(markup) -> set:
    if markup is None:
        return set()
    return {
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    }


# ---------------------------------------------------------------------------
# Кнопки действий под доставленным протоколом
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_part_carries_action_buttons(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)
    _patch_user(monkeypatch)

    long_protocol = "# Планёрка\n\n" + "\n\n".join(
        f"## Секция {i}\n" + "\n".join(f"- достаточно длинный пункт обсуждения номер {j}" for j in range(60))
        for i in range(8)
    )
    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result(history_id=7, protocol_text=long_protocol)
    )

    assert ok is True
    parts = [k for k in sent if "Часть" in k.get("text", "")]
    assert len(parts) > 1
    # кнопки только на последней части — под документом
    assert _keyboard_datas(parts[-1].get("reply_markup")) == {"proto_pdf_7", "proto_regen_7"}
    for part in parts[:-1]:
        assert part.get("reply_markup") is None


@pytest.mark.asyncio
async def test_no_buttons_without_history_id(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs)
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)
    _patch_user(monkeypatch)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result(history_id=None)
    )

    assert ok is True
    assert all(k.get("reply_markup") is None for k in sent)


@pytest.mark.asyncio
async def test_pdf_document_offers_only_regen(monkeypatch):
    documents = []

    async def fake_send_message(bot, chat_id, **kwargs):
        return object()

    async def fake_send_document(bot, chat_id, **kwargs):
        documents.append(kwargs)
        return object()

    async def fake_pdf(markdown_text, output_path):
        with open(output_path, "wb") as f:
            f.write(b"%PDF-1.4 fake")

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send_message)
    monkeypatch.setattr(result_sender, "safe_send_document", fake_send_document)
    import src.utils.pdf_converter as pdf_converter_module

    monkeypatch.setattr(
        pdf_converter_module, "convert_markdown_to_pdf_async", fake_pdf
    )
    _patch_user(monkeypatch, mode="pdf")

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, _request(), _result(history_id=9)
    )

    assert ok is True
    assert len(documents) == 1
    datas = _keyboard_datas(documents[0].get("reply_markup"))
    assert datas == {"proto_regen_9"}  # PDF уже в руках — предлагать его снова незачем


# ---------------------------------------------------------------------------
# Перегенерация из истории: без повторной транскрипции
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regenerate_uses_stored_transcription(monkeypatch):
    from src.services import protocol_actions

    row = {
        "id": 7,
        "user_id": 42,
        "file_name": "meeting.mp3",
        "transcription_text": "полная расшифровка встречи",
        "result_text": "# Старый протокол",
    }

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(
        db_module.history_repo, "save_processing_result", AsyncMock(return_value=101)
    )

    class FakeTemplateService:
        async def get_template_by_id(self, _tid):
            return SimpleNamespace(
                id=5, name="Протокол ОД (Поручения)",
                content="# {{ meeting_title }}\n{% if tasks_od %}## Поручения\n{{ tasks_od }}{% endif %}",
            )

    captured = {}

    class FakeLLMGen:
        def __init__(self, *args, **kwargs):
            pass

        async def optimized_llm_generation(self, transcription_result, template, request, metrics, meeting_type=None):
            captured["transcription"] = transcription_result.transcription
            return {
                "meeting_title": "Планёрка",
                "tasks_od": (
                    "1. Подготовить отчёт по кварталу — Отв. Иван Петров. "
                    "Срок — 25.07.2026\n"
                    "2. Согласовать бюджет проекта — Отв. Анна Сидорова"
                ),
            }

    import src.services.processing.llm_generation as llm_gen_module

    monkeypatch.setattr(llm_gen_module, "LLMGenerationService", FakeLLMGen)

    delivered = {}

    async def fake_send_result(bot, chat_id, user_id, request, result, progress_tracker=None):
        delivered["result"] = result
        return True

    monkeypatch.setattr(protocol_actions, "send_result_to_user", fake_send_result)

    ok = await protocol_actions.regenerate_protocol(
        bot=AsyncMock(), chat_id=1, telegram_user_id=1,
        history_id=7, template_id=5,
        user_service=SimpleNamespace(), template_service=FakeTemplateService(),
    )

    assert ok is True
    assert captured["transcription"] == "полная расшифровка встречи"
    result = delivered["result"]
    assert "Поручения" in result.protocol_text
    assert result.history_id == 101  # новая запись истории — кнопки работают по цепочке


@pytest.mark.asyncio
async def test_regenerate_refuses_without_transcription(monkeypatch):
    import src.database as db_module
    from src.services import protocol_actions

    monkeypatch.setattr(
        db_module.history_repo,
        "get_result_for_user",
        AsyncMock(return_value={"id": 7, "user_id": 42, "file_name": "a.mp3",
                                "transcription_text": "", "result_text": "x"}),
    )

    ok = await protocol_actions.regenerate_protocol(
        bot=AsyncMock(), chat_id=1, telegram_user_id=1,
        history_id=7, template_id=5,
        user_service=SimpleNamespace(), template_service=SimpleNamespace(),
    )
    assert ok is False


# ---------------------------------------------------------------------------
# Колбэки подключены и проверяют владельца
# ---------------------------------------------------------------------------

def test_protocol_actions_router_registered():
    import src.handlers.callbacks as cb

    assert "setup_protocol_actions_callbacks" in inspect.getsource(cb)


def test_callbacks_check_ownership():
    import src.handlers.callbacks.protocol_actions_callbacks as pac

    src_text = inspect.getsource(pac)
    assert "get_result_for_user" in src_text
    assert "from_user.id" in src_text
