"""
Вспомогательные функции для callback обработчиков.
"""

from aiogram.types import CallbackQuery
from loguru import logger


async def _safe_callback_answer(
    callback: CallbackQuery, text: str = None, show_alert: bool = False
):
    """Безопасный ответ на callback query с обработкой устаревших запросов

    ``show_alert`` поднимает ответ из всплывающей подсказки в модальное окно —
    для отказов, которые пользователь обязан увидеть (нет прав, устаревшая
    кнопка), а не заметить краем глаза.
    """
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as e:
        error_str = str(e).lower()
        # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
        error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
        if "query is too old" in error_str or "query id is invalid" in error_str:
            logger.debug(f"Callback query устарел: {error_msg_safe}")
        else:
            logger.warning(f"Ошибка ответа на callback: {error_msg_safe}")
