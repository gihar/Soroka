"""«Завершение обработки» — единый хвост конвейера (ADR-0003).

Один шов от генерации до доставки, которым владеют все три пути обработки
(основной, возобновление после карточки сопоставления, перегенерация из
истории). Внутри по порядку: генерация и сборка протокола, страховка замены
спикеров, кеширование, запись истории (всегда, независимо от доставки),
доставка, статус задачи очереди. Пути — тонкие адаптеры к :func:`complete_processing`.

Зависимости генерации и доставка приходят снаружи явно (``deps``/``delivery``):
модуль не собирает их сам и ничего не знает про Telegram — это делает его
тестируемым через собственный интерфейс, без обхода конструктора сервиса.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from src.database import queue_repo
from src.exceptions.processing import ProcessingError
from src.models.processing import ProcessingRequest, ProcessingResult
from src.performance.cache_system import performance_cache
from src.performance.metrics import PerformanceTimer, metrics_collector
from src.utils.text_processing import (
    humanize_speaker_labels_for_reader,
    normalize_hyphens,
    replace_speakers_in_text,
)

from .llm_generation import (
    effective_stage1_outcome,
    with_protocol_date_fallback,
    with_protocol_title_fallback,
)

# Доставка: способ донести готовый результат до пользователя. Возвращает True,
# только если тело протокола доставлено (см. result_sender.send_result_to_user).
Delivery = Callable[[ProcessingResult], Awaitable[bool]]

# Статус недоставленного протокола: сгенерирован, но до пользователя не дошёл.
_UNDELIVERED_TASK_ERROR = "Не удалось доставить результат пользователю"


@dataclass(frozen=True)
class CompletionDeps:
    """Явные зависимости генерации и учёта.

    ``llm_gen``   — генерация LLM и имя активной модели
                    (optimized_llm_generation, resolve_model_display_name).
    ``formatter`` — сборка текста протокола (format_protocol).
    ``history``   — запись истории и очистка временного файла
                    (save_processing_history, cleanup_temp_file).
    """

    llm_gen: Any
    formatter: Any
    history: Any


@dataclass(frozen=True)
class CompletionOutcome:
    """Итог завершения: собранный результат и факт его доставки."""

    result: ProcessingResult
    delivered: bool


async def complete_processing(
    request: ProcessingRequest,
    transcription_result: Any,
    template: Any,
    *,
    meeting_type: Optional[str],
    deps: CompletionDeps,
    delivery: Delivery,
    cache_key: Optional[str] = None,
    task_id: Optional[Any] = None,
    metrics: Any = None,
    temp_file_path: Optional[str] = None,
) -> CompletionOutcome:
    """Довести обработку от генерации до доставки и учёта — единый хвост.

    Порядок (ADR-0003): генерация и сборка → страховка замены спикеров → кеш
    (если ``cache_key``) → история (всегда) → доставка → статус задачи очереди
    (если ``task_id``: completed при доставке, иначе failed).

    Кеш и история идут ДО доставки и не зависят от её исхода: повторная загрузка
    того же файла попадёт в кеш и переотправится без повторной генерации, а
    история фиксирует факт генерации протокола даже при провале доставки.
    """
    result = await _assemble_result(
        request, transcription_result, template,
        deps=deps, meeting_type=meeting_type,
        metrics=metrics, temp_file_path=temp_file_path,
    )

    # Кеш после успешной генерации, независимо от доставки. Best-effort: сбой
    # кеша не должен обрушить уже сгенерированный протокол (кеш идёт ДО доставки).
    if cache_key:
        try:
            await performance_cache.set(
                cache_key, result, cache_type="processing_result",
            )
        except Exception as cache_error:
            logger.warning(f"Не удалось закешировать результат: {cache_error}")

    return await _record_and_deliver(
        result, request=request, deps=deps, delivery=delivery, task_id=task_id,
    )


async def deliver_cached(
    result: ProcessingResult,
    *,
    request: ProcessingRequest,
    deps: CompletionDeps,
    delivery: Delivery,
    task_id: Optional[Any] = None,
) -> CompletionOutcome:
    """Хвост для кеш-хита: результат уже сгенерирован и закеширован.

    Генерации и кеша нет — только учёт и доставка: свежая запись истории (её
    history_id даёт кнопки под протоколом), доставка, статус задачи очереди.
    Повторная загрузка того же файла попадает сюда и переотправляется без
    повторной генерации — задокументированный замысел кеша (ADR-0003).
    """
    return await _record_and_deliver(
        result, request=request, deps=deps, delivery=delivery, task_id=task_id,
    )


async def _record_and_deliver(
    result: ProcessingResult,
    *,
    request: ProcessingRequest,
    deps: CompletionDeps,
    delivery: Delivery,
    task_id: Optional[Any],
) -> CompletionOutcome:
    """Учёт и доставка: история (всегда, до доставки) → доставка → статус задачи."""
    # История — всегда, до доставки: history_id садится на результат, поэтому
    # кнопки действий под доставленным протоколом ссылаются на свежую запись.
    result.history_id = await deps.history.save_processing_history(request, result)

    delivered = await delivery(result)

    await _mark_queue_task(task_id, delivered)

    return CompletionOutcome(result=result, delivered=delivered)


async def _assemble_result(
    request: ProcessingRequest,
    transcription_result: Any,
    template: Any,
    *,
    deps: CompletionDeps,
    meeting_type: Optional[str],
    metrics: Any,
    temp_file_path: Optional[str],
) -> ProcessingResult:
    """Генерация LLM → форматирование → замена спикеров → сборка результата.

    Перенос логики бывшего ``ProcessingService._finalize_protocol``. ``metrics``
    опционален (перегенерация метрик не ведёт): при его отсутствии
    ``processing_duration`` = None, а метрические записи пропускаются.
    """
    llm_result = await deps.llm_gen.optimized_llm_generation(
        transcription_result, template, request, metrics,
        meeting_type=meeting_type,
    )
    if llm_result is None:
        raise ProcessingError(
            "LLM вернул пустой результат",
            request.file_name,
            "llm_empty_result",
        )

    # Реквизиты пересылки «наверх»: непустая дата и осмысленный титул. LLM почти
    # не извлекает дату из аудио и часто не называет встречу — детерминированные
    # фолбэки (meeting_date из запроса, иначе момент обработки) до рендера, чтобы
    # шапка `{% if date %}` не пряталась пустой, а титул не падал в безликое
    # «Резюме встречи». Единый момент обработки на оба поля — источник согласован.
    # Здесь — единственный шов всех путей генерации (основной, возобновление,
    # перегенерация), поэтому реквизиты гарантированы каждому.
    if isinstance(llm_result, dict):
        processing_moment = datetime.now()
        llm_result = with_protocol_date_fallback(
            llm_result,
            meeting_date=request.meeting_date,
            processing_moment=processing_moment,
        )
        llm_result = with_protocol_title_fallback(
            llm_result,
            meeting_date=request.meeting_date,
            processing_moment=processing_moment,
        )

    with PerformanceTimer("formatting", metrics_collector):
        if metrics is not None:
            metrics.formatting_duration = 0.1

        user_warnings: list = []
        protocol_text = deps.formatter.format_protocol(
            template, llm_result, transcription_result, warnings=user_warnings
        )

        # Страховка: подтверждённые имена участников заменяют метки спикеров.
        if request.speaker_mapping:
            protocol_text = replace_speakers_in_text(
                protocol_text, request.speaker_mapping
            )
            logger.info("Применена замена спикеров на имена участников")

        # Оставшиеся метки диаризации не должны доехать до читателя.
        protocol_text = humanize_speaker_labels_for_reader(
            protocol_text, user_warnings
        )

        # Детерминированная нормализация: неразрывный дефис к обычному, чтобы
        # «15‑минутки» не соседствовали с обычным дефисом в одном тексте.
        protocol_text = normalize_hyphens(protocol_text)

    # Очистка временного файла в фоне (только для внешних файлов).
    if request.is_external_file and temp_file_path:
        asyncio.create_task(deps.history.cleanup_temp_file(temp_file_path))

    llm_model_display_name = await deps.llm_gen.resolve_model_display_name()

    # Итоги ЭТАПА 1, фактически использованные генератором: при пропуске анализа
    # берутся из запроса/аргумента. Оседают в результат → историю, чтобы
    # перегенерация была консистентной без повторного анализа.
    effective_speaker_mapping, effective_meeting_type = effective_stage1_outcome(
        llm_result,
        speaker_mapping_fallback=request.speaker_mapping,
        meeting_type_fallback=meeting_type,
    )

    return ProcessingResult(
        transcription_result=transcription_result,
        protocol_text=protocol_text,
        template_used=(
            template.model_dump()
            if hasattr(template, "model_dump")
            else template.__dict__
        ),
        llm_provider_used=request.llm_provider,
        llm_model_used=llm_model_display_name,
        processing_duration=getattr(metrics, "total_duration", None),
        warnings=user_warnings,
        meeting_type=effective_meeting_type,
        speaker_mapping=effective_speaker_mapping,
    )


async def _mark_queue_task(task_id: Optional[Any], delivered: bool) -> None:
    """Best-effort финальный статус задачи очереди по факту доставки.

    Единая семантика для всех путей (бывший ``_mark_queue_task`` возобновления):
    доставлено → completed, иначе → failed. Без ``task_id`` (перегенерация,
    прямые вызовы) статус не трогаем.
    """
    if not task_id:
        return
    status = "completed" if delivered else "failed"
    error_message = None if delivered else _UNDELIVERED_TASK_ERROR
    try:
        await queue_repo.update_queue_task_status(
            str(task_id), status, error_message=error_message
        )
    except Exception as e:
        logger.warning(f"Не удалось обновить статус задачи {task_id}: {e}")
