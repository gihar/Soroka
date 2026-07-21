"""«Завершение обработки» — единый хвост конвейера (ADR-0003).

Инварианты модуля src/services/processing/completion.py через его публичный
интерфейс complete_processing: генерация → сборка → страховка спикеров → кеш →
история (всегда) → доставка → статус задачи. Три пути (основной, возобновление,
перегенерация) переиспользуют эти инварианты, поэтому дрейф невозможен.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services.processing.completion import (
    CompletionDeps,
    CompletionOutcome,
    complete_processing,
    deliver_cached,
)


def _request(**over) -> ProcessingRequest:
    base = dict(file_name="a.mp3", llm_provider="openai", user_id=1)
    base.update(over)
    return ProcessingRequest(**base)


def _deps(*, llm_result=None, model_name="GPT", history_id=42, formatter=None):
    llm_gen = SimpleNamespace(
        optimized_llm_generation=AsyncMock(
            return_value=llm_result if llm_result is not None else {"meeting_title": "Планёрка"}
        ),
        resolve_model_display_name=AsyncMock(return_value=model_name),
    )
    history = SimpleNamespace(
        save_processing_history=AsyncMock(return_value=history_id),
        cleanup_temp_file=AsyncMock(),
    )
    return CompletionDeps(
        llm_gen=llm_gen,
        formatter=formatter or SimpleNamespace(format_protocol=lambda *a, **k: "# Протокол"),
        history=history,
    )


async def _ok_delivery(result):
    return True


# ---------------------------------------------------------------------------
# Tracer bullet: генерация → доставка → outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generates_delivers_and_returns_outcome():
    deps = _deps()
    delivered = {}

    async def delivery(result):
        delivered["result"] = result
        return True

    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=delivery,
    )

    assert isinstance(outcome, CompletionOutcome)
    assert outcome.delivered is True
    assert isinstance(outcome.result, ProcessingResult)
    assert outcome.result.protocol_text == "# Протокол"
    # Доставка получила ровно собранный результат
    assert delivered["result"] is outcome.result


# ---------------------------------------------------------------------------
# История — всегда и ДО доставки: history_id виден доставке
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_written_before_delivery_and_id_visible():
    deps = _deps(history_id=555)
    seen_history_id = {}

    async def delivery(result):
        seen_history_id["value"] = result.history_id
        return True

    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=delivery,
    )

    # Доставка увидела history_id — история записана ДО неё.
    assert seen_history_id["value"] == 555
    assert outcome.result.history_id == 555
    deps.history.save_processing_history.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_written_even_when_delivery_fails():
    deps = _deps(history_id=555)

    async def failed_delivery(result):
        return False

    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=failed_delivery,
    )

    assert outcome.delivered is False
    deps.history.save_processing_history.assert_awaited_once()


# ---------------------------------------------------------------------------
# Кеш: безусловный при cache_key (даже при провале доставки), иначе не трогаем
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_caches_after_generation_independent_of_delivery(monkeypatch):
    import src.services.processing.completion as completion

    cache = SimpleNamespace(set=AsyncMock())
    monkeypatch.setattr(completion, "performance_cache", cache)

    async def failed_delivery(result):
        return False

    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=failed_delivery,
        cache_key="cache-key",
    )

    # Кеш выставлен несмотря на провал доставки.
    cache.set.assert_awaited_once()
    assert cache.set.await_args.args[0] == "cache-key"
    assert cache.set.await_args.args[1] is outcome.result


@pytest.mark.asyncio
async def test_no_cache_without_cache_key(monkeypatch):
    """Перегенерация вызывает с cache_key=None — кеш не трогается."""
    import src.services.processing.completion as completion

    cache = SimpleNamespace(set=AsyncMock())
    monkeypatch.setattr(completion, "performance_cache", cache)

    await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=_ok_delivery,
        cache_key=None,
    )

    cache.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_failure_does_not_break_delivery(monkeypatch):
    """Сбой кеша (best-effort) не мешает истории и доставке."""
    import src.services.processing.completion as completion

    cache = SimpleNamespace(set=AsyncMock(side_effect=RuntimeError("cache down")))
    monkeypatch.setattr(completion, "performance_cache", cache)

    deps = _deps()
    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
        cache_key="cache-key",
    )

    assert outcome.delivered is True
    deps.history.save_processing_history.assert_awaited_once()


# ---------------------------------------------------------------------------
# Страховка замены спикеров: применяется при request.speaker_mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_speakers_applied_when_mapping_present(monkeypatch):
    import src.services.processing.completion as completion

    replace_spy = MagicMock(return_value="# Протокол c именами")
    monkeypatch.setattr(completion, "replace_speakers_in_text", replace_spy)

    outcome = await complete_processing(
        request=_request(speaker_mapping={"SPEAKER_00": "Иван Петров"}),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=_ok_delivery,
    )

    replace_spy.assert_called_once()
    assert replace_spy.call_args.args[1] == {"SPEAKER_00": "Иван Петров"}
    assert "именами" in outcome.result.protocol_text


@pytest.mark.asyncio
async def test_replace_speakers_skipped_without_mapping(monkeypatch):
    import src.services.processing.completion as completion

    replace_spy = MagicMock(return_value="x")
    monkeypatch.setattr(completion, "replace_speakers_in_text", replace_spy)

    await complete_processing(
        request=_request(speaker_mapping=None),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=_ok_delivery,
    )

    replace_spy.assert_not_called()


# ---------------------------------------------------------------------------
# Статус задачи очереди: completed при доставке, failed иначе; None → не трогаем
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_marked_completed_when_delivered(monkeypatch):
    import src.services.processing.completion as completion

    update = AsyncMock()
    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", update)

    await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=_ok_delivery,
        task_id="TASK-1",
    )

    update.assert_awaited_once()
    assert update.await_args.args[0] == "TASK-1"
    assert update.await_args.args[1] == "completed"


@pytest.mark.asyncio
async def test_task_marked_failed_when_not_delivered(monkeypatch):
    import src.services.processing.completion as completion

    update = AsyncMock()
    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", update)

    async def failed_delivery(result):
        return False

    await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=failed_delivery,
        task_id="TASK-1",
    )

    update.assert_awaited_once()
    assert update.await_args.args[1] == "failed"


@pytest.mark.asyncio
async def test_no_task_status_without_task_id(monkeypatch):
    """Перегенерация вызывает с task_id=None — статус задачи не трогается."""
    import src.services.processing.completion as completion

    update = AsyncMock()
    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", update)

    await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=_ok_delivery,
        task_id=None,
    )

    update.assert_not_awaited()


# ---------------------------------------------------------------------------
# Полная сборка результата: template_used, llm_model_used, итоги ЭТАПА 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_result_assembly_captures_model_and_stage1():
    class _Template:
        def model_dump(self):
            return {"id": 5, "name": "Дейли", "content": "# {{ meeting_title }}"}

    deps = _deps(
        llm_result={
            "meeting_title": "Планёрка",
            "_meeting_type": "daily",
            "_speaker_mapping": {"SPEAKER_00": "Иван"},
        },
        model_name="gpt-5-mini",
    )

    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=_Template(),
        meeting_type=None,
        deps=deps,
        delivery=_ok_delivery,
    )

    result = outcome.result
    # Полный шаблон (model_dump целиком), а не {"name": …}
    assert result.template_used == {"id": 5, "name": "Дейли", "content": "# {{ meeting_title }}"}
    # Имя модели резолвится, а не None
    assert result.llm_model_used == "gpt-5-mini"
    # Итоги ЭТАПА 1 капчерятся в результат (→ история → консистентная перегенерация)
    assert result.meeting_type == "daily"
    assert result.speaker_mapping == {"SPEAKER_00": "Иван"}


@pytest.mark.asyncio
async def test_stage1_falls_back_to_request_when_llm_silent():
    deps = _deps(llm_result={"meeting_title": "Планёрка"})

    outcome = await complete_processing(
        request=_request(speaker_mapping={"SPEAKER_01": "Анна"}),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type="planning",
        deps=deps,
        delivery=_ok_delivery,
    )

    assert outcome.result.meeting_type == "planning"
    assert outcome.result.speaker_mapping == {"SPEAKER_01": "Анна"}


@pytest.mark.asyncio
async def test_metrics_optional_processing_duration_none():
    """Перегенерация зовёт без метрик (metrics=None): processing_duration=None,
    без падения на записи метрик."""
    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=_ok_delivery,
        metrics=None,
    )

    assert outcome.result.processing_duration is None


@pytest.mark.asyncio
async def test_metrics_total_duration_flows_into_result():
    outcome = await complete_processing(
        request=_request(),
        transcription_result=TranscriptionResult(transcription="текст"),
        template=SimpleNamespace(name="Дейли"),
        meeting_type=None,
        deps=_deps(),
        delivery=_ok_delivery,
        metrics=SimpleNamespace(total_duration=12.5),
    )

    assert outcome.result.processing_duration == 12.5


# ---------------------------------------------------------------------------
# deliver_cached: кеш-хит — учёт и доставка без генерации/кеша
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_cached_records_fresh_history_and_delivers(monkeypatch):
    import src.services.processing.completion as completion

    cache = SimpleNamespace(set=AsyncMock())
    monkeypatch.setattr(completion, "performance_cache", cache)
    update = AsyncMock()
    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", update)

    deps = _deps(history_id=321)
    # Кешированный результат приходит без history_id (кешируется до его записи).
    cached = ProcessingResult(
        transcription_result=TranscriptionResult(transcription="текст"),
        protocol_text="# Кешированный",
        template_used={"name": "Дейли"},
        llm_provider_used="openai",
    )

    seen = {}

    async def delivery(result):
        seen["history_id"] = result.history_id
        return True

    outcome = await deliver_cached(
        cached, request=_request(), deps=deps, delivery=delivery, task_id="TASK-1",
    )

    # Генерации нет — llm не звался; кеша нет — уже закеширован.
    deps.llm_gen.optimized_llm_generation.assert_not_awaited()
    cache.set.assert_not_awaited()
    # Свежая запись истории проставлена ДО доставки; задача помечена completed.
    assert seen["history_id"] == 321
    assert outcome.result is cached
    assert outcome.delivered is True
    assert update.await_args.args[1] == "completed"


@pytest.mark.asyncio
async def test_empty_llm_result_raises_processing_error():
    from src.exceptions.processing import ProcessingError

    deps = _deps(llm_result=None)
    deps.llm_gen.optimized_llm_generation = AsyncMock(return_value=None)

    with pytest.raises(ProcessingError):
        await complete_processing(
            request=_request(),
            transcription_result=TranscriptionResult(transcription="текст"),
            template=SimpleNamespace(name="Дейли"),
            meeting_type=None,
            deps=deps,
            delivery=_ok_delivery,
        )
