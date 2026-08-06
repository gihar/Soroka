"""Критика v4, craft: действия после доставки протокола.

Протокол доставлен — это не конец разговора: «PDF» и «Другой шаблон»
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
# Матрица кнопок формата: PDF и Word рядом, уже доставленный формат скрыт
# ---------------------------------------------------------------------------

def _rows_datas(markup):
    return [[btn.callback_data for btn in row] for row in markup.inline_keyboard]


def test_messages_mode_offers_pdf_and_word_side_by_side():
    kb = result_sender._protocol_actions_keyboard(7, "messages")
    rows = _rows_datas(kb)
    # PDF и Word — в одном ряду (рядом), перегенерация — отдельной строкой.
    assert rows[0] == ["proto_pdf_7", "proto_docx_7"]
    assert ["proto_regen_7"] in rows


def test_pdf_mode_hides_pdf_keeps_word():
    datas = _keyboard_datas(result_sender._protocol_actions_keyboard(9, "pdf"))
    assert datas == {"proto_docx_9", "proto_regen_9", "proto_header_9"}


def test_docx_mode_hides_word_keeps_pdf():
    datas = _keyboard_datas(result_sender._protocol_actions_keyboard(9, "docx"))
    assert datas == {"proto_pdf_9", "proto_regen_9", "proto_header_9"}


def test_no_keyboard_without_history_id():
    assert result_sender._protocol_actions_keyboard(None, "messages") is None


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
    # кнопки только на последней части — под документом (PDF + Word + перегенерация)
    assert _keyboard_datas(parts[-1].get("reply_markup")) == {
        "proto_pdf_7", "proto_docx_7", "proto_regen_7", "proto_header_7"
    }
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
async def test_pdf_document_offers_word_and_regen(monkeypatch):
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
    # PDF уже в руках — его не предлагаем снова, но Word ещё можно получить.
    assert datas == {"proto_docx_9", "proto_regen_9", "proto_header_9"}


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

        async def resolve_model_display_name(self):
            return "GPT"

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
async def test_regenerate_reuses_stored_mapping_and_type(monkeypatch):
    """Сохранённые тип встречи и сопоставление уходят в LLM — анализ не гоняется.

    Имена участников в перегенерации совпадают с уже отправленным протоколом, а
    новая запись истории наследует те же значения — цепочка остаётся консистентной.
    """
    import json

    from src.services import protocol_actions

    row = {
        "id": 7,
        "user_id": 42,
        "file_name": "meeting.mp3",
        "transcription_text": "полная расшифровка встречи",
        "result_text": "# Старый протокол",
        "speaker_mapping": json.dumps({"SPEAKER_00": "Иван Петров"}, ensure_ascii=False),
        "meeting_type": "daily",
    }

    import src.database as db_module

    save_mock = AsyncMock(return_value=101)
    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(db_module.history_repo, "save_processing_result", save_mock)

    class FakeTemplateService:
        async def get_template_by_id(self, _tid):
            return SimpleNamespace(
                id=5, name="Дейли", content="# {{ meeting_title }}",
            )

    captured = {}

    class FakeLLMGen:
        def __init__(self, *args, **kwargs):
            pass

        async def optimized_llm_generation(
            self, transcription_result, template, request, metrics, meeting_type=None
        ):
            captured["request_speaker_mapping"] = request.speaker_mapping
            captured["meeting_type_arg"] = meeting_type
            return {"meeting_title": "Планёрка"}

        async def resolve_model_display_name(self):
            return "GPT"

    import src.services.processing.llm_generation as llm_gen_module

    monkeypatch.setattr(llm_gen_module, "LLMGenerationService", FakeLLMGen)

    async def fake_send_result(bot, chat_id, user_id, request, result, progress_tracker=None):
        return True

    monkeypatch.setattr(protocol_actions, "send_result_to_user", fake_send_result)

    ok = await protocol_actions.regenerate_protocol(
        bot=AsyncMock(), chat_id=1, telegram_user_id=1,
        history_id=7, template_id=5,
        user_service=SimpleNamespace(), template_service=FakeTemplateService(),
    )

    assert ok is True
    # ЭТАП 1 пропущен: значения пришли в LLM-вызов из истории
    assert captured["request_speaker_mapping"] == {"SPEAKER_00": "Иван Петров"}
    assert captured["meeting_type_arg"] == "daily"
    # Новая запись истории наследует те же значения
    save_kwargs = save_mock.await_args.kwargs
    assert save_kwargs["speaker_mapping"] == {"SPEAKER_00": "Иван Петров"}
    assert save_kwargs["meeting_type"] == "daily"


@pytest.mark.asyncio
async def test_regenerate_heals_history_from_llm_result(monkeypatch):
    """Старая запись без сохранённого mapping: новая запись лечится итогом ЭТАПА 1.

    Иначе следующая перегенерация (v3) снова прогонит анализ и разойдётся с v2 —
    та же непоследовательность на уровень глубже. Поэтому effective-значения из
    llm_result оседают в новой записи, а не NULL.
    """
    from src.services import protocol_actions

    row = {
        "id": 7,
        "user_id": 42,
        "file_name": "meeting.mp3",
        "transcription_text": "полная расшифровка встречи",
        "result_text": "# Старый протокол",
        "speaker_mapping": None,  # старая запись — итогов анализа нет
        "meeting_type": None,
    }

    import src.database as db_module

    save_mock = AsyncMock(return_value=101)
    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(db_module.history_repo, "save_processing_result", save_mock)

    class FakeTemplateService:
        async def get_template_by_id(self, _tid):
            return SimpleNamespace(id=5, name="Дейли", content="# {{ meeting_title }}")

    class FakeLLMGen:
        def __init__(self, *args, **kwargs):
            pass

        async def optimized_llm_generation(
            self, transcription_result, template, request, metrics, meeting_type=None
        ):
            # ЭТАП 1 отработал заново — генератор вернул выведенные значения
            return {
                "meeting_title": "Планёрка",
                "_speaker_mapping": {"SPEAKER_00": "Мария Иванова"},
                "_meeting_type": "planning",
            }

        async def resolve_model_display_name(self):
            return "GPT"

    import src.services.processing.llm_generation as llm_gen_module

    monkeypatch.setattr(llm_gen_module, "LLMGenerationService", FakeLLMGen)

    async def fake_send_result(bot, chat_id, user_id, request, result, progress_tracker=None):
        return True

    monkeypatch.setattr(protocol_actions, "send_result_to_user", fake_send_result)

    ok = await protocol_actions.regenerate_protocol(
        bot=AsyncMock(), chat_id=1, telegram_user_id=1,
        history_id=7, template_id=5,
        user_service=SimpleNamespace(), template_service=FakeTemplateService(),
    )

    assert ok is True
    save_kwargs = save_mock.await_args.kwargs
    assert save_kwargs["speaker_mapping"] == {"SPEAKER_00": "Мария Иванова"}
    assert save_kwargs["meeting_type"] == "planning"


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


def _actions_handler(name: str):
    from unittest.mock import MagicMock

    import src.handlers.callbacks.protocol_actions_callbacks as pac

    router = pac.setup_protocol_actions_callbacks(
        user_service=MagicMock(), template_service=MagicMock()
    )
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == name
    )
    return pac, handler


@pytest.mark.asyncio
async def test_docx_callback_sends_word_from_history(monkeypatch):
    pac, handler = _actions_handler("protocol_docx_callback")
    monkeypatch.setattr(pac, "_safe_callback_answer", AsyncMock())

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value={
            "result_text": "# Планёрка\n\n## ✅ Решения\n1. ок",
            "file_name": "meeting.mp3",
        }),
    )

    import src.services.result_sender as rs

    captured = {}

    async def fake_send(bot, chat_id, protocol_text, source_file_name, output_mode):
        captured.update(mode=output_mode, text=protocol_text)
        return True

    monkeypatch.setattr(rs, "send_protocol_file", fake_send)

    cb = SimpleNamespace(
        data="proto_docx_7",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(chat=SimpleNamespace(id=1), answer=AsyncMock()),
        bot=AsyncMock(),
    )
    await handler(cb)

    assert captured["mode"] == "docx"
    assert captured["text"].startswith("# Планёрка")


@pytest.mark.asyncio
async def test_docx_callback_refuses_foreign_history(monkeypatch):
    pac, handler = _actions_handler("protocol_docx_callback")
    answers = []

    async def fake_answer(callback, text=None, **kwargs):
        answers.append(text)

    monkeypatch.setattr(pac, "_safe_callback_answer", fake_answer)

    import src.database as db_module

    # Чужой/очищенный id → репозиторий не отдаёт запись.
    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user", AsyncMock(return_value=None)
    )

    import src.services.result_sender as rs

    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(rs, "send_protocol_file", send_mock)

    cb = SimpleNamespace(
        data="proto_docx_7",
        from_user=SimpleNamespace(id=999),
        message=SimpleNamespace(chat=SimpleNamespace(id=1), answer=AsyncMock()),
        bot=AsyncMock(),
    )
    await handler(cb)

    send_mock.assert_not_awaited()
    assert answers and answers[-1]  # вежливый отказ, а не тишина


# ---------------------------------------------------------------------------
# Устойчивый разбор callback_data перегенерации
# ---------------------------------------------------------------------------

def _regen_go_handler(template_service=None):
    from unittest.mock import MagicMock

    import src.handlers.callbacks.protocol_actions_callbacks as pac

    router = pac.setup_protocol_actions_callbacks(
        user_service=MagicMock(), template_service=template_service or MagicMock()
    )
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "protocol_regen_go_callback"
    )
    return pac, handler


def _regen_callback(data: str):
    return SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        from_user=SimpleNamespace(id=1),
        bot=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_regen_go_dispatches_valid_ids(monkeypatch):
    class FakeTemplateService:
        async def get_template_by_id(self, _tid):
            return SimpleNamespace(id=5, name="Дейли")

    pac, handler = _regen_go_handler(FakeTemplateService())
    monkeypatch.setattr(pac, "safe_edit_text", AsyncMock())
    monkeypatch.setattr(pac, "_safe_callback_answer", AsyncMock())

    import src.services.protocol_actions as pa

    captured = {}

    async def fake_regen(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(pa, "regenerate_protocol", fake_regen)

    await handler(_regen_callback("proto_regen_go_7_5"))

    assert captured["history_id"] == 7
    assert captured["template_id"] == 5


@pytest.mark.asyncio
async def test_regen_go_rejects_malformed_data_gracefully(monkeypatch):
    """Нечисловой callback_data — вежливый отказ, а не серверная ошибка в логах."""
    from loguru import logger

    pac, handler = _regen_go_handler()

    answers = []

    async def fake_answer(callback, text=None, **kwargs):
        answers.append(text)

    monkeypatch.setattr(pac, "_safe_callback_answer", fake_answer)
    monkeypatch.setattr(pac, "safe_edit_text", AsyncMock())

    import src.services.protocol_actions as pa

    regen_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(pa, "regenerate_protocol", regen_mock)

    errors = []
    sink_id = logger.add(lambda m: errors.append(m.record["message"]), level="ERROR")
    try:
        await handler(_regen_callback("proto_regen_go_7_abc"))
    finally:
        logger.remove(sink_id)

    regen_mock.assert_not_awaited()
    assert answers and answers[-1]  # пользователь получил вежливый отказ
    assert not any("protocol_regen_go_callback" in e for e in errors)


# ---------------------------------------------------------------------------
# Обкатка модели через перегенерацию (#118): экран виден только администратору
# ---------------------------------------------------------------------------

def _as_admin(monkeypatch, allowed: bool) -> None:
    """Права администратора — единственное, что делит эти экраны надвое."""
    import src.utils.admin_utils as admin_utils

    monkeypatch.setattr(admin_utils, "is_admin", lambda _uid: allowed)


def _stored_row(**overrides):
    row = {
        "id": 7,
        "user_id": 42,
        "file_name": "meeting.mp3",
        "template_id": 5,
        "transcription_text": "полная расшифровка встречи",
        "result_text": "# Старый протокол",
    }
    row.update(overrides)
    return row


def _presets():
    return [
        {"key": "openrouter-gpt-5-mini", "name": "GPT-5 mini"},
        {"key": "qwen-token-plan", "name": "Qwen3.7 Plus"},
    ]


def _model_callback(data: str, user_id: int = 1):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(chat=SimpleNamespace(id=1), answer=AsyncMock()),
        bot=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_model_picker_offers_every_enabled_preset_to_admin(monkeypatch):
    from src.ux.protocol_actions_callback_data import ProtoModelGo, ProtoModels

    pac, handler = _actions_handler("protocol_models_callback")
    _as_admin(monkeypatch, True)
    monkeypatch.setattr(pac, "_safe_callback_answer", AsyncMock())

    edited = {}

    async def fake_edit(_message, text, **kwargs):
        edited.update(text=text, markup=kwargs.get("reply_markup"))

    monkeypatch.setattr(pac, "safe_edit_text", fake_edit)

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value=_stored_row()),
    )
    monkeypatch.setattr(
        db_module.model_preset_repo, "get_enabled",
        AsyncMock(return_value=_presets()),
    )

    data = ProtoModels(history_id=7)
    await handler(_model_callback(data.pack()), data)

    datas = _keyboard_datas(edited["markup"])
    assert ProtoModelGo(history_id=7, preset_key="qwen-token-plan").pack() in datas
    assert ProtoModelGo(history_id=7, preset_key="openrouter-gpt-5-mini").pack() in datas
    texts = {btn.text for row in edited["markup"].inline_keyboard for btn in row}
    assert "Qwen3.7 Plus" in texts  # выбирают по имени, а не по ключу


@pytest.mark.asyncio
async def test_model_picker_refuses_non_admin(monkeypatch):
    """Не-администратор получает отказ, а не список моделей."""
    from src.ux.protocol_actions_callback_data import ProtoModels

    pac, handler = _actions_handler("protocol_models_callback")
    _as_admin(monkeypatch, False)

    answers = []

    async def fake_answer(_callback, text=None, **kwargs):
        answers.append(text)

    monkeypatch.setattr(pac, "_safe_callback_answer", fake_answer)
    edit_mock = AsyncMock()
    monkeypatch.setattr(pac, "safe_edit_text", edit_mock)

    import src.database as db_module

    presets_mock = AsyncMock(return_value=_presets())
    monkeypatch.setattr(db_module.model_preset_repo, "get_enabled", presets_mock)

    data = ProtoModels(history_id=7)
    await handler(_model_callback(data.pack(), user_id=999), data)

    presets_mock.assert_not_awaited()  # список моделей даже не запрашивался
    edit_mock.assert_not_awaited()
    assert answers and "администратор" in answers[-1]


def _regen_screen_handler():
    from unittest.mock import MagicMock

    import src.handlers.callbacks.protocol_actions_callbacks as pac

    class FakeTemplateService:
        async def get_all_templates(self):
            return [SimpleNamespace(id=5, name="Дейли")]

    router = pac.setup_protocol_actions_callbacks(
        user_service=MagicMock(), template_service=FakeTemplateService()
    )
    handler = next(
        h.callback for h in router.callback_query.handlers
        if h.callback.__name__ == "protocol_regen_callback"
    )
    return pac, handler


async def _regen_screen_datas(monkeypatch, *, admin: bool) -> set:
    pac, handler = _regen_screen_handler()
    _as_admin(monkeypatch, admin)
    monkeypatch.setattr(pac, "_safe_callback_answer", AsyncMock())

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value=_stored_row()),
    )

    cb = _model_callback("proto_regen_7")
    await handler(cb)

    markup = cb.message.answer.await_args.kwargs["reply_markup"]
    return _keyboard_datas(markup)


@pytest.mark.asyncio
async def test_regen_screen_offers_model_choice_to_admin(monkeypatch):
    from src.ux.protocol_actions_callback_data import ProtoModels

    datas = await _regen_screen_datas(monkeypatch, admin=True)

    assert ProtoModels(history_id=7).pack() in datas
    assert "proto_regen_go_7_5" in datas  # выбор шаблона на месте


@pytest.mark.asyncio
async def test_regen_screen_hides_model_choice_from_everyone_else(monkeypatch):
    from src.ux.protocol_actions_callback_data import ProtoModels

    datas = await _regen_screen_datas(monkeypatch, admin=False)

    assert ProtoModels(history_id=7).pack() not in datas
    assert "proto_regen_go_7_5" in datas  # обычный путь не пострадал


@pytest.mark.asyncio
async def test_model_go_regenerates_with_chosen_preset_and_stored_template(monkeypatch):
    """Выбранный пресет уходит в перегенерацию; активный пресет бота не трогается."""
    from src.ux.protocol_actions_callback_data import ProtoModelGo

    pac, handler = _actions_handler("protocol_model_go_callback")
    _as_admin(monkeypatch, True)
    monkeypatch.setattr(pac, "_safe_callback_answer", AsyncMock())
    monkeypatch.setattr(pac, "safe_edit_text", AsyncMock())

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value=_stored_row()),
    )
    qwen = {"key": "qwen-token-plan", "name": "Qwen3.7 Plus", "is_enabled": True}
    monkeypatch.setattr(
        db_module.model_preset_repo, "get_by_key", AsyncMock(return_value=qwen)
    )
    set_active = AsyncMock()
    monkeypatch.setattr(db_module.app_settings_repo, "set_active_model_key", set_active)

    import src.services.protocol_actions as pa

    captured = {}

    async def fake_regen(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(pa, "regenerate_protocol", fake_regen)

    data = ProtoModelGo(history_id=7, preset_key="qwen-token-plan")
    await handler(_model_callback(data.pack()), data)

    assert captured["history_id"] == 7
    assert captured["template_id"] == 5  # шаблон записи — меняется только модель
    assert captured["preset"] == qwen
    set_active.assert_not_awaited()  # обкатка не переводит на модель всех разом


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored_preset",
    [None, {"key": "qwen-token-plan", "name": "Qwen3.7 Plus", "is_enabled": False}],
    ids=["удалён", "выключен"],
)
async def test_model_go_refuses_a_preset_that_left_between_screens(
    monkeypatch, stored_preset
):
    """Пресет успели удалить или выключить, пока экран висел — запуска нет.

    Экран выбора живёт своей жизнью: между показом списка и нажатием кнопки
    администратор мог убрать пресет в /models. Молча уйти на него значило бы
    генерировать адресом, которого больше нет.
    """
    from src.ux.protocol_actions_callback_data import ProtoModelGo

    pac, handler = _actions_handler("protocol_model_go_callback")
    _as_admin(monkeypatch, True)

    answers = []

    async def fake_answer(_callback, text=None, **kwargs):
        answers.append(text)

    monkeypatch.setattr(pac, "_safe_callback_answer", fake_answer)
    monkeypatch.setattr(pac, "safe_edit_text", AsyncMock())

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value=_stored_row()),
    )
    monkeypatch.setattr(
        db_module.model_preset_repo, "get_by_key",
        AsyncMock(return_value=stored_preset),
    )

    import src.services.protocol_actions as pa

    regen_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(pa, "regenerate_protocol", regen_mock)

    data = ProtoModelGo(history_id=7, preset_key="qwen-token-plan")
    await handler(_model_callback(data.pack()), data)

    regen_mock.assert_not_awaited()
    assert answers and "недоступна" in answers[-1]


@pytest.mark.asyncio
async def test_model_go_refuses_non_admin(monkeypatch):
    """Кнопка модели, доставшаяся не-администратору, не запускает перегенерацию."""
    from src.ux.protocol_actions_callback_data import ProtoModelGo

    pac, handler = _actions_handler("protocol_model_go_callback")
    _as_admin(monkeypatch, False)

    answers = []

    async def fake_answer(_callback, text=None, **kwargs):
        answers.append(text)

    monkeypatch.setattr(pac, "_safe_callback_answer", fake_answer)
    monkeypatch.setattr(pac, "safe_edit_text", AsyncMock())

    import src.services.protocol_actions as pa

    regen_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(pa, "regenerate_protocol", regen_mock)

    data = ProtoModelGo(history_id=7, preset_key="qwen-token-plan")
    await handler(_model_callback(data.pack(), user_id=999), data)

    regen_mock.assert_not_awaited()
    assert answers and "администратор" in answers[-1]


@pytest.mark.asyncio
async def test_model_picker_refuses_record_without_transcription(monkeypatch):
    """Без сохранённой расшифровки перегенерации нет — и на экране модели тоже."""
    from src.ux.protocol_actions_callback_data import ProtoModels

    pac, handler = _actions_handler("protocol_models_callback")
    _as_admin(monkeypatch, True)

    answers = []

    async def fake_answer(_callback, text=None, **kwargs):
        answers.append(text)

    monkeypatch.setattr(pac, "_safe_callback_answer", fake_answer)
    edit_mock = AsyncMock()
    monkeypatch.setattr(pac, "safe_edit_text", edit_mock)

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value=_stored_row(transcription_text="")),
    )

    data = ProtoModels(history_id=7)
    await handler(_model_callback(data.pack()), data)

    edit_mock.assert_not_awaited()  # экрана выбора не было
    assert answers and "Расшифровка не сохранена" in answers[-1]


# ---------------------------------------------------------------------------
# Сводка называет модель ровно тогда, когда её выбирали
# ---------------------------------------------------------------------------

async def _delivered_texts(monkeypatch, request, result) -> list:
    sent = []

    async def fake_send(bot, chat_id, **kwargs):
        sent.append(kwargs.get("text", ""))
        return object()

    monkeypatch.setattr(result_sender, "safe_send_message", fake_send)
    _patch_user(monkeypatch)

    ok = await result_sender.send_result_to_user(
        AsyncMock(), 1, 1, request, result
    )
    assert ok is True
    return sent


@pytest.mark.asyncio
async def test_summary_names_the_model_when_it_was_chosen(monkeypatch):
    """Обкатка: без имени модели два протокола на одной записи не различить."""
    request = ProcessingRequest(
        file_name="meeting.mp3", llm_provider="openai", user_id=1,
        model_preset_key="qwen-token-plan",
    )
    result = _result(history_id=7)
    result.llm_model_used = "Qwen3.7 Plus"

    texts = await _delivered_texts(monkeypatch, request, result)

    assert any("Модель: Qwen3.7 Plus" in t for t in texts)


@pytest.mark.asyncio
async def test_summary_keeps_model_out_of_ordinary_delivery(monkeypatch):
    """Обычная доставка не обрастает техникой: модель по-прежнему уходит в логи."""
    result = _result(history_id=7)
    result.llm_model_used = "GPT-5 mini"

    texts = await _delivered_texts(monkeypatch, _request(), result)

    assert not any("Модель" in t for t in texts)


@pytest.mark.asyncio
async def test_regen_screen_still_refuses_record_without_transcription(monkeypatch):
    """Старая запись без расшифровки объясняет отказ, а не показывает пикер."""
    pac, handler = _regen_screen_handler()
    _as_admin(monkeypatch, True)

    answers = []

    async def fake_answer(_callback, text=None, **kwargs):
        answers.append(text)

    monkeypatch.setattr(pac, "_safe_callback_answer", fake_answer)

    import src.database as db_module

    monkeypatch.setattr(
        db_module.history_repo, "get_result_for_user",
        AsyncMock(return_value=_stored_row(transcription_text="")),
    )

    cb = _model_callback("proto_regen_7")
    await handler(cb)

    cb.message.answer.assert_not_awaited()
    assert answers and "Расшифровка не сохранена" in answers[-1]
