"""Меню команд Telegram — то, что открывается по кнопке «/».

`set_my_commands` не вызывался нигде, поэтому меню было пустым: команды жили
только в приветственном пузыре, к которому никто не возвращается. Даже опытный
пользователь печатал их вслепую.

Список короткий намеренно: пять пунктов — это верхняя граница того, что читают
списком, а /start в меню не нужен (его уже нажали, чтобы начать).
"""

from typing import Any

from aiogram.types import BotCommand
from loguru import logger

# Порядок — по частоте нужды, а не по алфавиту.
COMMANDS: tuple[tuple[str, str], ...] = (
    ("help", "Как получить протокол"),
    ("templates", "Шаблоны протокола"),
    ("settings", "Формат вывода и сопоставление спикеров"),
    ("feedback", "Написать разработчику"),
)


async def publish_command_menu(bot: Any) -> None:
    """Опубликовать меню команд. Best-effort: сбой не должен ронять запуск."""
    try:
        await bot.set_my_commands(
            [BotCommand(command=name, description=text) for name, text in COMMANDS]
        )
        logger.info(f"Меню команд опубликовано: {len(COMMANDS)} пунктов")
    except Exception as e:
        logger.warning(f"Не удалось опубликовать меню команд: {e}")
