"""Алерты администраторам о сбоях, которые видит только сервер.

Есть отказы, которых пользователь не замечает: протокол приходит, просто без
раздела. Лог о таком знает, но лог никто не читает в момент события — поэтому
здесь отдельный канал: текст уходит администраторам из ``settings.admins``.

Канал доставки один на все поводы: и расхождение ответа модели с брифом, и
исчерпание ресурса провайдера. Второй канал в воркере очереди означал бы вторую
копию правил доставки и второй троттлинг — расходящиеся по мере правок.

Модуль знает только «как донести текст», не «когда»: решение принимает тот, кто
заметил сбой (``LLMGenerationService``, воркер очереди). Отправка best-effort —
сбой уведомления не должен обрушить уже сгенерированный протокол.

Троттлинг — по поводу: при исчерпании ресурса падает каждая задача очереди, и
без окна админов завалит потоком одинаковых сообщений. Считается он отдельно по
каждому поводу, иначе первый же квотный инцидент проглотил бы сообщение о
расхождении с брифом — событие другой природы, о котором надо знать сразу.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional

from aiogram import Bot
from loguru import logger

from src.config import settings
from src.models.validation import BriefConformance

# Один повод — одно сообщение в этом окне, сколько бы задач ни упало.
ALERT_THROTTLE = timedelta(minutes=10)

# Поводы алертов. Окно троттлинга у каждого своё.
REASON_BRIEF_MISMATCH = "brief_mismatch"
REASON_INSUFFICIENT_CREDITS = "insufficient_credits"
REASON_QUOTA_EXHAUSTED = "quota_exhausted"

# Один Bot на весь процесс для алертов (по образцу file_service._get_file_bot):
# создаётся лениво, переиспользуется, aiohttp-сессия закрывается свипом на
# shutdown'е в src/bot.py.
_alert_bot: Optional[Bot] = None

# Когда по каждому поводу уходил последний алерт.
_last_alert_at: Dict[str, datetime] = {}


def _get_alert_bot() -> Bot:
    """Вернуть общий Bot для алертов администраторам."""
    global _alert_bot
    if _alert_bot is None:
        _alert_bot = Bot(token=settings.telegram_token)
    return _alert_bot


def reset_alert_throttle() -> None:
    """Забыть отправленные алерты: окна начинаются заново (нужно тестам)."""
    global _last_alert_at
    _last_alert_at = {}


def _is_throttled(reason: str, now: datetime) -> bool:
    """Об этом поводе уже сообщали внутри окна."""
    last_at = _last_alert_at.get(reason)
    return last_at is not None and now - last_at < ALERT_THROTTLE


def _remember_alert(reason: str, now: datetime) -> None:
    """Запомнить момент отправки (новый словарь, без правки прежнего)."""
    global _last_alert_at
    _last_alert_at = {**_last_alert_at, reason: now}


def _keys_line(title: str, keys: tuple) -> str:
    return f"{title}: {', '.join(keys)}\n" if keys else ""


def _incident_details(exc: Exception) -> str:
    """Модель и обрезанный ответ провайдера — общая справка для алертов о сбое."""
    details = getattr(exc, "details", None) or {}
    model = details.get("model") if isinstance(details, dict) else None

    raw = str(exc)
    if len(raw) > 300:
        raw = raw[:297] + "..."

    model_line = f"Модель: {model}\n" if model else ""
    return f"{model_line}Детали: {raw}\n\n"


def build_brief_mismatch_alert(
    conformance: BriefConformance,
    *,
    model_name: Optional[str],
) -> str:
    """Текст алерта о расхождении ответа модели с ключами брифа.

    Называет модель: пресетов несколько, а строгие схемы применяет не каждая
    модель (ADR-0007) — без имени администратору некуда идти.
    """
    return (
        "🚨 Протокол: модель ответила не по контракту\n\n"
        "Набор полей ответа разошёлся с шаблоном — разделы протокола потеряны "
        "молча.\n\n"
        f"Шаблон: {conformance.template_name}\n"
        f"Модель: {model_name or '?'}\n"
        + _keys_line("Не пришли", conformance.missing_keys)
        + _keys_line("Лишние", conformance.unexpected_keys)
        + "\n➡️ Проверьте, применяет ли модель строгую схему ответа "
        "(/check_model), и при необходимости смените активный пресет."
    )


def build_credits_alert(exc: Exception) -> str:
    """Текст алерта администраторам об исчерпании кредитов провайдера (HTTP 402)."""
    return (
        "🚨 LLM: закончились кредиты (HTTP 402)\n\n"
        "Запросы к LLM-провайдеру падают — пользователи сейчас получают "
        "«Сервис временно недоступен».\n\n"
        + _incident_details(exc)
        + "➡️ Пополните баланс провайдера "
        "(например, https://openrouter.ai/settings/credits)."
    )


def build_quota_alert(exc: Exception, *, switched_to: Optional[str] = None) -> str:
    """Текст алерта об исчерпании квоты подписки.

    Совет противоположен кредитному: пополнять нечего — квота вернётся в
    следующем периоде, а работать сейчас можно только с другого пресета
    (CONTEXT.md, ADR-0007).

    ``switched_to`` — имя пресета, на который автовозврат уже перевёл бота.
    Тогда шаг администратора другой: просить сменить пресет, который бот сменил
    сам, значит слать в /models за уже сделанной работой.
    """
    if switched_to:
        next_step = (
            f"Активный пресет переключён на «{switched_to}» — следующие протоколы "
            "идут на нём.\n\n"
            "➡️ Квота вернётся в следующем периоде подписки. Вернуть прежний "
            "пресет можно в /models."
        )
    else:
        next_step = (
            "➡️ Квота вернётся в следующем периоде подписки. Чтобы протоколы шли "
            "сейчас, смените активный пресет (/models)."
        )

    return (
        "🚨 LLM: исчерпана квота подписки\n\n"
        "Запросы к модели падают — пользователи сейчас получают отказ.\n\n"
        + _incident_details(exc)
        + next_step
    )


async def notify_admins(text: str, *, reason: str) -> None:
    """Разослать текст всем администраторам (best-effort, ошибки — в лог).

    ``reason`` называет повод: он же ключ окна троттлинга.
    """
    if not settings.admins:
        logger.warning(f"Алерт админам ({reason}) не отправлен: список ADMINS пуст")
        return

    now = datetime.now()
    if _is_throttled(reason, now):
        logger.debug(f"Алерт админам ({reason}) пропущен: троттлинг")
        return
    _remember_alert(reason, now)

    from src.utils.telegram_safe import safe_send_message

    bot = _get_alert_bot()
    for admin_id in settings.admins:
        try:
            await safe_send_message(bot, admin_id, text, disable_web_page_preview=True)
        except Exception as send_error:
            logger.error(f"Не удалось уведомить админа {admin_id}: {send_error}")
    logger.info(f"Алерт админам ({reason}) отправлен: {settings.admins}")


async def notify_brief_mismatch(
    conformance: BriefConformance,
    *,
    model_name: Optional[str] = None,
) -> None:
    """Сообщить администраторам о расхождении ответа модели с ключами брифа."""
    await notify_admins(
        build_brief_mismatch_alert(conformance, model_name=model_name),
        reason=REASON_BRIEF_MISMATCH,
    )


async def notify_insufficient_credits(exc: Exception) -> None:
    """Сообщить администраторам об исчерпании кредитов провайдера."""
    await notify_admins(build_credits_alert(exc), reason=REASON_INSUFFICIENT_CREDITS)


async def notify_quota_exhausted(
    exc: Exception, *, switched_to: Optional[str] = None
) -> None:
    """Сообщить администраторам об исчерпании квоты подписки.

    ``switched_to`` называет пресет, на который увёл автовозврат (если увёл):
    одно сообщение вместо двух — и повод, и то, что бот с ним сделал.
    """
    await notify_admins(
        build_quota_alert(exc, switched_to=switched_to),
        reason=REASON_QUOTA_EXHAUSTED,
    )
