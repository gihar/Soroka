"""Политика сбоя обработки — одна на все пути прогона (ADR-0010, ADR-0011).

Прогон падает в двух местах: в воркере очереди (до паузы или без неё) и при
закрытии Сессии сопоставления (после паузы). Раньше у каждого места была своя
ветка сбоя, и они разошлись: уведомление администратора жило только в воркере
— поэтому четырнадцать отказов из пятнадцати не дошли ни до кого, — а статус
задачи очереди проставляло только возобновление, и упавшая в воркере задача
навсегда оставалась в ``processing``.

Теперь сбой обрабатывается одной функцией. Чем пути различаются — только
каналом к пользователю: воркер показывает сбой в трекере прогресса, закрытие
паузы — отдельным сообщением. Канал приходит снаружи (``notify_user``); тексту
по причине сбоя он учится у ``error_presentation`` сам.
"""

from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from src.database import queue_repo
from src.services import provider_failure

# Как сказать пользователю о сбое: канал получает исключение и сам подбирает
# текст по причине (сырой текст провайдера пользователю не показывается).
NotifyUser = Callable[[Exception], Awaitable[None]]


async def fail_processing(
    error: Exception,
    *,
    task_id: Optional[Any],
    notify_user: NotifyUser,
) -> None:
    """Довести сбой прогона до всех, кому он адресован.

    По порядку: задача очереди → failed (если ``task_id``), пользователь —
    через свой канал, администратор — решением ``provider_failure`` («когда
    писать» живёт там). Каждый шаг best-effort: сбой одного не отменяет
    остальные и не подменяет исходную ошибку — её решает судьбу вызывающий.
    """
    # opt(exception=True), а не exc_info=True: loguru не печатает traceback по
    # exc_info, зато любой kwarg включает message.format() — и текст ошибки с
    # фигурными скобками (сырой payload провайдера) ронял бы сам обработчик.
    logger.opt(exception=True).error(
        f"Сбой обработки (задача {task_id}, {type(error).__name__}): {error}"
    )

    await _mark_task_failed(task_id, error)

    try:
        await notify_user(error)
    except Exception as notify_error:
        logger.error(f"Не удалось уведомить пользователя о сбое: {notify_error}")

    try:
        await provider_failure.report_llm_failure(error)
    except Exception as admin_error:
        logger.error(f"Не удалось уведомить админов о сбое провайдера: {admin_error}")


async def _mark_task_failed(task_id: Optional[Any], error: Exception) -> None:
    """Best-effort: строка очереди не должна навсегда остаться в ``processing``."""
    if not task_id:
        return
    try:
        await queue_repo.update_queue_task_status(
            str(task_id), "failed", error_message=str(error)
        )
    except Exception as e:
        logger.warning(f"Не удалось обновить статус задачи {task_id}: {e}")
