"""Что делает бот, когда вызов LLM упал.

Здесь живёт «когда»: опознать класс отказа, решить, писать ли администраторам,
и запускать ли автовозврат. Доставкой занимается ``admin_alerts``, который знает
только «как донести текст» — разделение из его же докстринга, и оно осталось.

Точка одна, потому что путей два. Задача, вставшая на карточке сопоставления,
уходит из воркера очереди (``paused = True; return``), и её продолжает коллбэк.
Прод 08–15.09.2026: пятнадцать ударов в стену, четырнадцать из них — после
паузы, где уведомлять было некому, и ноль сообщений администраторам за
одиннадцать дней. Правило «когда писать» не может жить в ветке одного из путей.

Классы отказа разведены по действию администратора, а не по виду сбоя
(CONTEXT.md): кредиты лечит пополнение, квоту — следующий период или другой
пресет, неоплаченный доступ — продление подписки или другой пресет навсегда.
Под ними сетка: отказ провайдера без диагноза — сам по себе повод написать.

Автовозврат запускают только опознанные стены. У незнакомого отказа диагноза
нет по определению, а «тихо переехать на случайного провайдера хуже, чем
постоять» (ADR-0007): одна сетевая икота увела бы бота с рабочего адреса.
"""

from typing import Optional, Tuple

from loguru import logger

from src.services import admin_alerts, preset_failover
from src.services.error_presentation import (
    is_access_not_purchased,
    is_insufficient_credits,
    is_quota_exhausted,
    is_unknown_provider_refusal,
)


async def _fallback_is_configured() -> bool:
    """Назначен ли резервный пресет вообще.

    Отличает «резерв не задан» от «резерв есть, но не сработал»: первое лечится
    одним нажатием в /models, второе — разбирательством, и админу стоит знать,
    какой из двух случаев перед ним.

    Прочитать не удалось — считаем, что задан: промолчать честнее, чем заявить
    администратору то, чего мы не проверили.
    """
    from src.database import app_settings_repo

    try:
        return bool(await app_settings_repo.get_fallback_model_key())
    except Exception as e:
        logger.warning(f"Не удалось прочитать резервный пресет: {e}")
        return True


async def _move_to_reserve() -> Tuple[Optional[str], bool]:
    """Перевести активный пресет на резервный. Имя нового и «резерв назначен»."""
    switched_to = await preset_failover.return_to_fallback()
    if switched_to:
        return switched_to, True
    return None, await _fallback_is_configured()


async def report_llm_failure(exc: Exception) -> None:
    """Отреагировать на сбой LLM-вызова: уведомить админов, где это уместно.

    Зовётся из общей ветки сбоя, куда приходит что угодно — битый контейнер,
    нехватка памяти, отвалившийся ffmpeg. Поэтому сетка ловит только то, на что
    ответил провайдер (``is_unknown_provider_refusal``), а остальное проходит
    молча: это сбой не про LLM, и администратору он не адресован.

    Best-effort по духу ``admin_alerts``: вызывающий ловит исключение отсюда,
    чтобы сбой уведомления не подменил собой сбой обработки.
    """
    text = str(exc)

    if is_quota_exhausted(text):
        switched_to, configured = await _move_to_reserve()
        await admin_alerts.notify_quota_exhausted(
            exc, switched_to=switched_to, fallback_configured=configured
        )
        return

    if is_access_not_purchased(text):
        switched_to, configured = await _move_to_reserve()
        await admin_alerts.notify_access_not_purchased(
            exc, switched_to=switched_to, fallback_configured=configured
        )
        return

    if is_insufficient_credits(text):
        # Кредиты лечатся пополнением за минуту — уводить бота с провайдера незачем.
        await admin_alerts.notify_insufficient_credits(exc)
        return

    if is_unknown_provider_refusal(text):
        await admin_alerts.notify_unknown_provider_refusal(exc)
