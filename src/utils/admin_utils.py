"""
Утилиты для работы с правами администратора
"""

from loguru import logger

from config import settings


def is_admin(user_id: int) -> bool:
    """
    Проверить, является ли пользователь администратором
    
    Args:
        user_id: Telegram ID пользователя
        
    Returns:
        True если пользователь является администратором, иначе False
    """
    if not settings.admins:
        # Если список администраторов пуст, логируем предупреждение
        logger.warning("Список администраторов (ADMINS) не настроен в .env файле")
        return False
    
    return user_id in settings.admins

