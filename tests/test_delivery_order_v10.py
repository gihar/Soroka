"""Критика v10: оговорки идут ДО протокола, а не после него.

Два дефекта одного шва:

1. Предупреждения отправлялись отдельными пузырями ПОСЛЕ тела протокола, так
   что каждый прогон заканчивался сомнением в вещи, которую пользователь сейчас
   перешлёт. Хуже: в режимах ``pdf``/``docx`` оговорка остаётся в чате и с
   файлом не едет — руководство получает поручения «Участнику N» без всякого
   объяснения.
2. Дата в шапке могла быть днём обработки, и об этом никто не говорил.

Оба лечатся одним движением: всё, что читателю нужно знать О документе, входит
в сводку, которая идёт перед документом и пересылается вместе с ним.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.processing import ProcessingRequest, ProcessingResult, TranscriptionResult
from src.ux.message_builder import MessageBuilder

_WARNING = "⚠️ Шаблон «Дейли» слабо совпал с содержимым встречи."


# ---------------------------------------------------------------------------
# Сводка несёт оговорки и метку подставленной даты
# ---------------------------------------------------------------------------


def test_summary_carries_warnings():
    text = MessageBuilder.processing_complete_message({
        "template_used": {"name": "Дейли"},
        "llm_provider_used": "openai",
        "warnings": [_WARNING],
    })
    assert "слабо совпал" in text


def test_summary_carries_every_warning():
    text = MessageBuilder.processing_complete_message({
        "template_used": {"name": "Дейли"},
        "llm_provider_used": "openai",
        "warnings": [_WARNING, "ℹ️ Не всех говорящих удалось сопоставить."],
    })
    assert "слабо совпал" in text
    assert "Не всех говорящих" in text


def test_summary_notes_assumed_date():
    text = MessageBuilder.processing_complete_message({
        "template_used": {"name": "Дейли"},
        "llm_provider_used": "openai",
        "date_is_assumed": True,
    })
    assert "день обработки" in text
    # Голос «что + шаг»: named the problem AND the next step.
    assert "Дата и название" in text


def test_summary_stays_silent_when_date_is_known():
    text = MessageBuilder.processing_complete_message({
        "template_used": {"name": "Дейли"},
        "llm_provider_used": "openai",
        "date_is_assumed": False,
    })
    assert "день обработки" not in text


def test_summary_without_notes_is_unchanged():
    """Ничего пустого: без оговорок сводка остаётся прежними 2-4 строками."""
    text = MessageBuilder.processing_complete_message({
        "template_used": {"name": "Дейли"},
        "llm_provider_used": "openai",
    })
    assert text.startswith("✅ <b>Протокол готов</b>")
    assert text.count("\n") <= 2
    assert text.strip() == text


# ---------------------------------------------------------------------------
# Доставка: сводка (с оговорками) — до тела, отдельных пузырей после нет
# ---------------------------------------------------------------------------


def _result(**over) -> ProcessingResult:
    base = dict(
        transcription_result=TranscriptionResult(transcription="т"),
        protocol_text="# П\n\n## ✅ Решения\n- ок",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
    )
    base.update(over)
    return ProcessingResult(**base)


@pytest.fixture
def sent_texts(monkeypatch):
    """Перехват всех исходящих сообщений в порядке отправки."""
    from src.services import result_sender

    sent: list[str] = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs.get("text", ""))
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)

    import src.services.user_service as user_service_module

    class FakeUserService:
        async def get_user_by_telegram_id(self, _uid):
            return SimpleNamespace(protocol_output_mode="messages")

    monkeypatch.setattr(user_service_module, "UserService", FakeUserService)
    return sent


@pytest.mark.asyncio
async def test_warning_travels_in_summary_before_body(sent_texts):
    from src.services import result_sender

    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, request, _result(warnings=[_WARNING])
    )

    assert ok is True
    warning_index = next(i for i, t in enumerate(sent_texts) if "слабо совпал" in t)
    body_index = next(i for i, t in enumerate(sent_texts) if "Решения" in t)
    assert warning_index < body_index, "оговорка обязана предшествовать протоколу"


@pytest.mark.asyncio
async def test_warning_is_not_repeated_after_body(sent_texts):
    from src.services import result_sender

    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)

    await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, request, _result(warnings=[_WARNING])
    )

    assert sum("слабо совпал" in t for t in sent_texts) == 1


@pytest.mark.asyncio
async def test_last_message_is_the_protocol_not_a_caveat(sent_texts):
    """Правило пика-и-конца: разговор заканчивается артефактом."""
    from src.services import result_sender

    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)

    await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, request, _result(warnings=[_WARNING])
    )

    assert "Решения" in sent_texts[-1]


@pytest.mark.asyncio
async def test_file_mode_puts_caveat_in_chat_before_the_file(monkeypatch, sent_texts):
    """В режиме PDF оговорка обязана быть в сводке — иначе с файлом не поедет."""
    from src.services import result_sender

    async def fake_file(*args, **kwargs):
        return True

    monkeypatch.setattr(result_sender, "send_protocol_file", fake_file)

    import src.services.user_service as user_service_module

    class PdfUserService:
        async def get_user_by_telegram_id(self, _uid):
            return SimpleNamespace(protocol_output_mode="pdf")

    monkeypatch.setattr(user_service_module, "UserService", PdfUserService)

    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)
    await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, request, _result(warnings=[_WARNING])
    )

    assert any("слабо совпал" in t for t in sent_texts)


# ---------------------------------------------------------------------------
# Хвост помечает подставленную дату
# ---------------------------------------------------------------------------


def _request(**over) -> ProcessingRequest:
    base = dict(file_name="a.mp3", llm_provider="openai", user_id=1)
    base.update(over)
    return ProcessingRequest(**base)


def _deps(llm_result):
    return CompletionDepsFactory(llm_result)


def CompletionDepsFactory(llm_result):
    from src.services.processing.completion import CompletionDeps

    return CompletionDeps(
        llm_gen=SimpleNamespace(
            optimized_llm_generation=AsyncMock(return_value=llm_result),
            resolve_model_display_name=AsyncMock(return_value="GPT"),
        ),
        formatter=SimpleNamespace(
            format_protocol=lambda *a, **k: "# Протокол"
        ),
        history=SimpleNamespace(
            save_processing_history=AsyncMock(return_value=1),
            cleanup_temp_file=AsyncMock(),
        ),
    )


async def _ok_delivery(result):
    return True


@pytest.mark.asyncio
async def test_tail_marks_date_as_assumed_without_any_source():
    from src.services.processing.completion import complete_processing

    outcome = await complete_processing(
        request=_request(meeting_date=None),
        transcription_result=TranscriptionResult(transcription="т"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps({"meeting_title": "Планёрка", "date": ""}),
        delivery=_ok_delivery,
    )

    assert outcome.result.date_is_assumed is True


@pytest.mark.asyncio
async def test_tail_does_not_mark_date_from_request():
    from src.services.processing.completion import complete_processing

    outcome = await complete_processing(
        request=_request(meeting_date="15 июля 2026"),
        transcription_result=TranscriptionResult(transcription="т"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps({"meeting_title": "Планёрка", "date": ""}),
        delivery=_ok_delivery,
    )

    assert outcome.result.date_is_assumed is False


@pytest.mark.asyncio
async def test_tail_does_not_mark_date_from_llm():
    from src.services.processing.completion import complete_processing

    outcome = await complete_processing(
        request=_request(meeting_date=None),
        transcription_result=TranscriptionResult(transcription="т"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps({"meeting_title": "Планёрка", "date": "20 октября 2024"}),
        delivery=_ok_delivery,
    )

    assert outcome.result.date_is_assumed is False
