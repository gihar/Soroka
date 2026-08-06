"""Алерты администраторам о сбоях, которые видит только сервер.

Есть отказы, которых пользователь не замечает: протокол приходит, просто без
раздела. Лог о таком знает, но лог никто не читает в момент события — поэтому
здесь отдельный канал: текст уходит администраторам из ``settings.admins``.

Модуль знает только «как донести текст», не «когда»: решение принимает тот, кто
заметил расхождение (``LLMGenerationService``). Отправка best-effort — сбой
уведомления не должен обрушить уже сгенерированный протокол.
"""

from typing import Optional

from aiogram import Bot
from loguru import logger

from src.config import settings
from src.models.validation import BriefConformance

# Один Bot на весь процесс для алертов (по образцу file_service._get_file_bot):
# создаётся лениво, переиспользуется, aiohttp-сессия закрывается свипом на
# shutdown'е в src/bot.py.
_alert_bot: Optional[Bot] = None


def _get_alert_bot() -> Bot:
    """Вернуть общий Bot для алертов администраторам."""
    global _alert_bot
    if _alert_bot is None:
        _alert_bot = Bot(token=settings.telegram_token)
    return _alert_bot


def _keys_line(title: str, keys: tuple) -> str:
    return f"{title}: {', '.join(keys)}\n" if keys else ""


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


async def notify_admins(text: str) -> None:
    """Разослать текст всем администраторам (best-effort, ошибки — в лог)."""
    if not settings.admins:
        logger.warning("Алерт админам не отправлен: список ADMINS пуст")
        return

    from src.utils.telegram_safe import safe_send_message

    bot = _get_alert_bot()
    for admin_id in settings.admins:
        try:
            await safe_send_message(bot, admin_id, text, disable_web_page_preview=True)
        except Exception as send_error:
            logger.error(f"Не удалось уведомить админа {admin_id}: {send_error}")


async def notify_brief_mismatch(
    conformance: BriefConformance,
    *,
    model_name: Optional[str] = None,
) -> None:
    """Сообщить администраторам о расхождении ответа модели с ключами брифа."""
    await notify_admins(build_brief_mismatch_alert(conformance, model_name=model_name))
