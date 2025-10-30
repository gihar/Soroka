"""
Сервис для временного хранения состояния обработки во время ожидания подтверждения сопоставления
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from loguru import logger


class MappingStateCache:
    """
    Кеш для состояния сопоставления во время ожидания подтверждения пользователя
    """
    
    def __init__(self, ttl_seconds: int = 3600):
        """
        Инициализация кеша
        
        Args:
            ttl_seconds: Время жизни записи в секундах (по умолчанию 1 час)
        """
        self._cache: Dict[int, Dict[str, Any]] = {}
        self._timestamps: Dict[int, datetime] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
    
    async def save_state(self, user_id: int, state_data: Dict[str, Any]) -> None:
        """
        Сохранить состояние обработки для пользователя
        
        Args:
            user_id: ID пользователя
            state_data: Данные состояния (speaker_mapping, diarization_data, request_data и т.д.)
        """
        try:
            self._cache[user_id] = state_data
            self._timestamps[user_id] = datetime.now()
            logger.debug(f"Состояние обработки сохранено для пользователя {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении состояния для пользователя {user_id}: {e}", exc_info=True)
            raise
    
    async def load_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Загрузить состояние обработки для пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Данные состояния или None, если не найдено или истек срок
        """
        try:
            # Проверяем наличие записи
            if user_id not in self._cache:
                logger.debug(f"Состояние для пользователя {user_id} не найдено")
                return None
            
            # Проверяем срок действия
            timestamp = self._timestamps.get(user_id)
            if timestamp and datetime.now() - timestamp > self._ttl:
                logger.warning(f"Состояние для пользователя {user_id} истекло (старше {self._ttl})")
                # Очищаем истекшее состояние
                self._cache.pop(user_id, None)
                self._timestamps.pop(user_id, None)
                return None
            
            state_data = self._cache.get(user_id)
            logger.debug(f"Состояние обработки загружено для пользователя {user_id}")
            return state_data
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке состояния для пользователя {user_id}: {e}", exc_info=True)
            return None
    
    async def clear_state(self, user_id: int) -> None:
        """
        Очистить состояние обработки для пользователя
        
        Args:
            user_id: ID пользователя
        """
        try:
            self._cache.pop(user_id, None)
            self._timestamps.pop(user_id, None)
            logger.debug(f"Состояние обработки очищено для пользователя {user_id}")
        except Exception as e:
            logger.warning(f"Ошибка при очистке состояния для пользователя {user_id}: {e}")
    
    async def update_mapping(self, user_id: int, new_mapping: Dict[str, str]) -> bool:
        """
        Обновить только сопоставление в сохраненном состоянии
        
        Args:
            user_id: ID пользователя
            new_mapping: Новое сопоставление
            
        Returns:
            True если успешно, False если состояние не найдено
        """
        try:
            if user_id not in self._cache:
                logger.warning(f"Попытка обновить mapping для пользователя {user_id}, но состояние не найдено")
                return False
            
            # Обновляем mapping в сохраненном состоянии
            if 'request_data' in self._cache[user_id]:
                self._cache[user_id]['request_data']['speaker_mapping'] = new_mapping
            
            self._cache[user_id]['speaker_mapping'] = new_mapping
            logger.debug(f"Mapping обновлен для пользователя {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении mapping для пользователя {user_id}: {e}", exc_info=True)
            return False
    
    def cleanup_expired(self) -> int:
        """
        Очистить все истекшие записи
        
        Returns:
            Количество удаленных записей
        """
        now = datetime.now()
        expired_users = [
            user_id for user_id, timestamp in self._timestamps.items()
            if now - timestamp > self._ttl
        ]
        
        for user_id in expired_users:
            self._cache.pop(user_id, None)
            self._timestamps.pop(user_id, None)
        
        if expired_users:
            logger.info(f"Очищено {len(expired_users)} истекших состояний")
        
        return len(expired_users)


# Глобальный экземпляр кеша
mapping_state_cache = MappingStateCache(ttl_seconds=3600)

