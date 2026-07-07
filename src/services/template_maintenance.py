"""Идемпотентная миграция системных шаблонов: переименование и удаление сирот.

Запускается на старте бота из TemplateService.init_default_templates() ДО
синхронизации код→БД. Работает только над системными строками (created_by IS NULL),
поэтому пользовательские шаблоны никогда не затрагиваются. Безопасна к повторному запуску.
"""
from loguru import logger

# old (как лежит в БД) -> new (русское имя)
RENAME_MAP = {
    "Daily Standup": "Дейли",
    "Sprint Retrospective": "Ретроспектива спринта",
    "Backlog Refinement": "Груминг бэклога",
}

# системные шаблоны-сироты (нет в коде) на удаление
REMOVE_NAMES = [
    "Мастер-класс",
    "Семинар и дискуссия",
    "Стратегическая сессия руководства",
    "Протокол с детализацией говорящих",
]


async def apply_template_maintenance(templates) -> dict:
    """Переименовать англоязычные системные шаблоны и удалить системных сирот.

    Returns:
        dict со счётчиками {renamed, deduped, deleted}.
    """
    renamed = 0
    deduped = 0
    deleted = 0

    for old_name, new_name in RENAME_MAP.items():
        if await templates.system_template_exists(new_name):
            # целевое имя уже есть (повторный/частичный прогон) — убрать устаревший дубль
            deduped += await templates.delete_system_template_by_name(old_name)
        else:
            renamed += await templates.rename_system_template(old_name, new_name)

    for name in REMOVE_NAMES:
        deleted += await templates.delete_system_template_by_name(name)

    result = {"renamed": renamed, "deduped": deduped, "deleted": deleted}
    logger.info("Обслуживание шаблонов завершено: {}", result)
    return result
