"""Критика v4, harden: кастомные шаблоны без молчаливых отказов, честные алиасы, FSM без ловушки."""

import inspect
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Legacy-модули внутри хендлеров используют голый `from services import ...`.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.processing import (  # noqa: E402
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services.processing.protocol_formatter import ProtocolFormatter  # noqa: E402
from src.services.template_library import TemplateLibrary  # noqa: E402
from src.services.template_variables import unknown_variables  # noqa: E402

# ---------------------------------------------------------------------------
# Реестр переменных: опечатка видна при сохранении, а не вечной пустой секцией
# ---------------------------------------------------------------------------

def test_unknown_variable_gets_close_match_suggestion():
    result = unknown_variables("# {{ meeting_title }}\n{{ decisons }}")
    assert result == {"decisons": "decisions"}


def test_known_variables_pass_clean():
    assert unknown_variables("{{ decisions }}\n{{ action_items }}") == {}


def test_all_system_template_variables_are_known():
    for template in TemplateLibrary().get_all_templates():
        assert unknown_variables(template["content"]) == {}, template["name"]


@pytest.mark.asyncio
async def test_preview_warns_about_unknown_variable(monkeypatch):
    import src.handlers.template_handlers as th

    sent = {}

    async def fake_answer(message, text, **kwargs):
        sent["text"] = text
        return object()

    monkeypatch.setattr(th, "safe_answer", fake_answer)

    message = MagicMock()
    message.answer = AsyncMock()
    await th._show_template_preview(
        message,
        {
            "template_name": "Мой",
            "template_content": "{% if decisons %}## Решения\n{{ decisons }}{% endif %}",
        },
        SimpleNamespace(render_template=lambda c, v: "отрендерено"),
    )
    assert "decisons" in sent["text"]
    assert "decisions" in sent["text"]  # подсказка «возможно, вы имели в виду»


# ---------------------------------------------------------------------------
# Совместимость шаблона: предупреждение доходит до чата, а не умирает в логах
# ---------------------------------------------------------------------------

def test_low_compatibility_produces_warning():
    formatter = ProtocolFormatter()
    warnings: list = []
    template = {
        "content": (
            "# {{ meeting_title }}\n"
            "{% if alpha %}## А\n{{ alpha }}{% endif %}\n"
            "{% if beta %}## Б\n{{ beta }}{% endif %}\n"
            "{% if gamma %}## В\n{{ gamma }}{% endif %}\n"
            "{% if delta %}## Г\n{{ delta }}{% endif %}\n"
            "{% if discussion %}## 💬 Обсуждение\n{{ discussion }}{% endif %}"
        )
    }
    llm_result = {
        "meeting_title": "Планёрка",
        "discussion": "Достаточно длинный текст обсуждения, чтобы рендер не свалился в fallback. " * 3,
    }
    formatter.format_protocol(
        template, llm_result, TranscriptionResult(transcription="т"), warnings=warnings
    )
    assert warnings, "низкая совместимость должна дать предупреждение"
    assert "шаблон" in warnings[0].lower()


@pytest.mark.asyncio
async def test_result_warnings_delivered_to_chat(monkeypatch):
    from src.services import result_sender

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

    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)
    result = ProcessingResult(
        transcription_result=TranscriptionResult(transcription="т"),
        protocol_text="# П\n\n## ✅ Решения\n- ок",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
        llm_model_used=None,
        warnings=["⚠️ Шаблон «Дейли» слабо совпал с содержимым встречи."],
    )

    ok = await result_sender.send_result_to_user(AsyncMock(), 1, 1, request, result)

    assert ok is True
    texts = " ".join(kwargs["text"] for kwargs in sent)
    assert "слабо совпал" in texts


# ---------------------------------------------------------------------------
# Алиасы: /t /s /h /st /fb — реальные команды, заглушка «Выполняю…» удалена
# ---------------------------------------------------------------------------

def test_aliases_wired_into_real_command_filters():
    import src.handlers.command_handlers as ch

    src_text = inspect.getsource(ch)
    assert 'Command("templates", "t")' in src_text
    assert 'Command("settings", "s")' in src_text
    assert 'Command("help", "h")' in src_text
    assert 'Command("feedback", "fb")' in src_text


def test_status_alias_wired():
    import src.handlers.admin_handlers as ah

    assert 'Command("status", "st")' in inspect.getsource(ah)


def test_alias_stub_loop_removed():
    import src.ux.quick_actions as qa

    src_text = inspect.getsource(qa)
    assert "Выполняю команду" not in src_text
    assert "COMMAND_ALIASES" not in src_text


# ---------------------------------------------------------------------------
# FSM создания шаблона: команды и отмена не превращаются в контент
# ---------------------------------------------------------------------------

def _template_router(service=None):
    import src.handlers.template_handlers as th

    return th, th.setup_template_handlers(service or MagicMock())


def _state_handler(router, name):
    return next(h.callback for h in router.message.handlers if h.callback.__name__ == name)


class _FakeState:
    def __init__(self):
        self.data = {}
        self.state = "waiting_for_content"
        self.cleared = False

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.state = state

    async def get_data(self):
        return self.data

    async def clear(self):
        self.cleared = True


@pytest.mark.asyncio
async def test_slash_text_not_swallowed_as_content(monkeypatch):
    th, router = _template_router()
    monkeypatch.setattr(th, "safe_answer", AsyncMock())
    handler = _state_handler(router, "template_content_handler")

    message = MagicMock()
    message.text = "/cancel"
    message.answer = AsyncMock()
    state = _FakeState()

    await handler(message, state)

    assert "template_content" not in state.data
    assert state.cleared is True


def test_creation_prompts_offer_cancel_button():
    import src.handlers.template_handlers as th

    src_text = inspect.getsource(th)
    assert 'callback_data="cancel_template_creation"' in src_text
    # оба промпта (имя из двух точек входа + контент) дают кнопку отмены
    assert src_text.count("reply_markup=_cancel_keyboard()") >= 3
    # и есть обработчик, который чистит состояние
    assert 'F.data == "cancel_template_creation"' in src_text
