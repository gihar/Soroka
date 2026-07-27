"""Обработчик ошибок не должен падать сам — и не должен сливать payload провайдера.

Прод 22.07.2026, 17:53 и 18:00: при исчерпании кредитов OpenRouter (HTTP 402)
в логах вместо разбора ошибки появлялось

    ERROR | speaker_mapping_callbacks:wrapper:174 - Ошибка в
            speaker_mapping_confirm_callback: "'error'"

Механизм: ``logger.error(f"...{error}", exc_info=True)``. ``exc_info`` — идиома
stdlib logging; loguru её не знает, но ЛЮБОЙ kwarg включает у него
``message.format(*args, **kwargs)``. В сообщение к тому моменту уже подставлен
текст ошибки с сырым payload ``{'error': {...}}``, и ``str.format`` читает это как
placeholder с именем ``'error'`` → KeyError.

KeyError вылетал ИЗ вызова логгера, обрывая ``_handle_resume_failure`` до
``_mark_queue_task`` и до уведомления пользователя: задача навсегда оставалась в
статусе ``processing``, а человек получал общую отписку обёртки.

Тот же ``exc_info=True`` объясняет, почему за 14 дней в проде не появилось ни
одного traceback при 53 ERROR — он никогда не печатал traceback.
"""
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Сырой payload прода: с user_id и max_tokens — ровно то, что нельзя показывать.
RAW_402 = (
    "Error code: 402 - {'error': {'message': 'This request requires more credits, "
    "or fewer max_tokens. You requested up to 65536 tokens, but can only afford "
    "56162.', 'code': 402}, 'user_id': 'user_2lpA5W2gt60hAGWIkHfhzCdz90y'}"
)

_SRC = Path(__file__).resolve().parent.parent / "src"


# ---------------------------------------------------------------------------
# Механизм: логирование не должно падать на фигурных скобках в тексте ошибки
# ---------------------------------------------------------------------------

def test_no_exc_info_left_in_sources():
    """Страж: ``exc_info`` в исходниках — мина.

    loguru его игнорирует (traceback не печатается), а как kwarg он включает
    ``.format()`` по сообщению: любая ошибка с фигурными скобками в тексте
    роняет сам обработчик ошибок. Правильная идиома — ``logger.opt(exception=True)``.
    """
    offenders = [
        f"{path.relative_to(_SRC)}:{i}"
        for path in _SRC.rglob("*.py")
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        # Комментарии не в счёт: объяснять, почему exc_info нельзя, — полезно.
        if "exc_info" in line.split("#", 1)[0]
    ]
    assert offenders == [], f"exc_info остался в: {offenders}"


def test_logging_error_text_with_braces_does_not_raise():
    """Прямая проверка механизма на живом loguru."""
    from loguru import logger

    # Так падало: kwarg → message.format() → KeyError("'error'").
    with pytest.raises(KeyError):
        logger.error(f"Ошибка: {RAW_402}", exc_info=True)

    # Так правильно: traceback есть, форматирования нет.
    logger.opt(exception=False).error(f"Ошибка: {RAW_402}")


# ---------------------------------------------------------------------------
# Путь возобновления: сообщение пользователю и статус задачи
# ---------------------------------------------------------------------------

def _service():
    import src.services.processing.processing_service as pss

    return pss.ProcessingService.__new__(pss.ProcessingService)


async def _run_resume_failure(monkeypatch, error: Exception):
    """Прогнать _handle_resume_failure, вернув (тексты пользователю, статус задачи)."""
    import src.services.processing.processing_service as pss

    sent = []

    async def fake_send(bot=None, chat_id=None, text=None, **kw):
        sent.append(text)
        return SimpleNamespace(message_id=1)

    monkeypatch.setattr(pss, "safe_send_message", fake_send)

    marked = {}

    async def fake_mark(self, task_id, status, error_message=None):
        marked["status"] = status

    monkeypatch.setattr(pss.ProcessingService, "_mark_queue_task", fake_mark)

    service = _service()
    with pytest.raises(Exception):  # обработчик всегда пробрасывает наружу
        await service._handle_resume_failure(
            error, user_id=1, chat_id=1, bot=SimpleNamespace(), task_id="t1"
        )
    return sent, marked


async def test_resume_402_does_not_leak_provider_payload(monkeypatch):
    from src.exceptions.processing import LLMInsufficientCreditsError

    sent, _ = await _run_resume_failure(
        monkeypatch,
        LLMInsufficientCreditsError(RAW_402, provider="openai", model="gpt-5"),
    )

    assert sent, "пользователь должен получить сообщение, а не тишину"
    text = "\n".join(sent)
    assert "user_id" not in text
    assert "max_tokens" not in text
    assert "Error code: 402" not in text
    assert "openrouter.ai" not in text.lower()


async def test_resume_402_advice_is_credits_aware(monkeypatch):
    """«Пополните кредиты» — не «начните обработку заново»: перезапуск не поможет."""
    from src.exceptions.processing import LLMInsufficientCreditsError

    sent, _ = await _run_resume_failure(
        monkeypatch,
        LLMInsufficientCreditsError(RAW_402, provider="openai", model="gpt-5"),
    )

    text = "\n".join(sent).lower()
    # Честно сказано, что это на нашей стороне и временно.
    assert "временно" in text or "позже" in text
    # Совет «начните заново» для кончившихся кредитов бесполезен.
    assert "начните обработку заново" not in text


async def test_resume_402_still_marks_queue_task_failed(monkeypatch):
    """Задача не должна остаться в ``processing``: раньше KeyError обрывал обработчик."""
    from src.exceptions.processing import LLMInsufficientCreditsError

    _, marked = await _run_resume_failure(
        monkeypatch,
        LLMInsufficientCreditsError(RAW_402, provider="openai", model="gpt-5"),
    )

    assert marked.get("status") == "failed"


async def test_resume_other_errors_keep_their_hint(monkeypatch):
    """Не-кредитные ошибки не потеряли осмысленную подсказку."""
    sent, _ = await _run_resume_failure(monkeypatch, RuntimeError("connection reset"))

    text = "\n".join(sent).lower()
    assert "api" in text or "несколько минут" in text


async def test_resume_402_end_to_end_survives_logging(monkeypatch):
    """Полный путь возобновления при 402: наружу ProcessingError, не KeyError.

    Именно здесь KeyError вылетал из логгера и обрывал обработчик.
    """
    import src.services.processing.completion as completion
    import src.services.processing.processing_service as pss
    import src.ux.progress_tracker as pt_mod
    from src.exceptions.processing import LLMInsufficientCreditsError, ProcessingError
    from src.models.processing import ProcessingRequest, TranscriptionResult
    from src.services.mapping_session import MappingSession

    service = _service()
    service.llm_gen = SimpleNamespace(
        optimized_llm_generation=AsyncMock(
            side_effect=LLMInsufficientCreditsError(
                RAW_402, provider="openai", model="gpt-5"
            )
        ),
        resolve_model_display_name=AsyncMock(return_value="GPT"),
    )
    service.formatter = SimpleNamespace(format_protocol=lambda *a, **k: "# П")
    service.history = SimpleNamespace(
        save_processing_history=AsyncMock(return_value=1),
        cleanup_temp_file=AsyncMock(),
    )

    monkeypatch.setattr(
        pt_mod.ProgressFactory, "create_file_processing_tracker",
        AsyncMock(return_value=SimpleNamespace(
            start_stage=AsyncMock(), complete_all=AsyncMock(),
            bot=SimpleNamespace(), chat_id=1,
        )),
    )
    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", AsyncMock())
    monkeypatch.setattr(pss, "safe_send_message", AsyncMock())
    monkeypatch.setattr(
        pss.ProcessingService, "_mark_queue_task", AsyncMock()
    )

    session = MappingSession(
        request=ProcessingRequest(
            file_name="m.mp3", llm_provider="openai", user_id=1, template_id=5
        ),
        transcription_result=TranscriptionResult(transcription="текст"),
        speaker_mapping={}, meeting_type="daily", temp_file_path=None,
        cache_key=None, task_id="t1",
        metrics=SimpleNamespace(llm_duration=0.0, protocol_quality_score=0.0),
        template=SimpleNamespace(id=5, name="Дейли", content="# {{ meeting_title }}"),
    )

    with pytest.raises(ProcessingError):
        await service.continue_processing_after_mapping_confirmation(
            session=session, confirmed_mapping={},
            bot=SimpleNamespace(), chat_id=1,
        )


def test_credits_detection_has_single_source_of_truth():
    """Детектор 402 живёт в одном месте, воркер к нему делегирует."""
    from src.services import error_presentation
    from src.services.task_queue_manager import TaskQueueManager

    assert error_presentation.is_insufficient_credits(RAW_402.lower())
    assert not error_presentation.is_insufficient_credits("файл слишком большой")
    # Воркер не держит вторую копию правил.
    assert "error_presentation" in inspect.getsource(TaskQueueManager)
