"""Сессия сопоставления: приостановленная обработка в ожидании подтверждения.

Типизированная замена dict-ам со строковыми ключами: хранилище in-memory,
поэтому объекты живут как есть — без model_dump()/регидрации. Атомарный
``take`` закрывает гонку двойного подтверждения: взял — владеешь, второй
тап получает None.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

from loguru import logger

from src.models.processing import ProcessingRequest, TranscriptionResult
from src.performance.metrics import ProcessingMetrics


@dataclass
class MappingSession:
    """Всё, что нужно, чтобы возобновить обработку после подтверждения."""

    request: ProcessingRequest
    transcription_result: TranscriptionResult
    speaker_mapping: Dict[str, str]
    meeting_type: str
    temp_file_path: Optional[str]
    cache_key: Optional[str]
    task_id: Optional[str]
    metrics: ProcessingMetrics
    # Спикеры с доставленным фрагментом записи: их цитата уже в подписи
    # фрагмента, карточка сопоставления её не дублирует (в т.ч. при перерисовках).
    speakers_with_audio: Set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.now)


class MappingSessionStore:
    """Хранилище сессий сопоставления по user_id с ленивым TTL."""

    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: Dict[int, MappingSession] = {}
        self._timestamps: Dict[int, datetime] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def _evict_if_expired(self, user_id: int) -> None:
        timestamp = self._timestamps.get(user_id)
        if timestamp and datetime.now() - timestamp > self._ttl:
            logger.warning(f"Сессия сопоставления пользователя {user_id} истекла (старше {self._ttl})")
            self._sessions.pop(user_id, None)
            self._timestamps.pop(user_id, None)

    def save(self, user_id: int, session: MappingSession) -> None:
        """Сохранить сессию при постановке обработки на паузу."""
        self._sessions[user_id] = session
        self._timestamps[user_id] = datetime.now()
        logger.debug(f"Сессия сопоставления сохранена для пользователя {user_id}")

    def peek(self, user_id: int) -> Optional[MappingSession]:
        """Прочитать сессию, не изымая (для UI смены/выбора/отмены)."""
        self._evict_if_expired(user_id)
        return self._sessions.get(user_id)

    def update_mapping(self, user_id: int, new_mapping: Dict[str, str]) -> bool:
        """Обновить сопоставление в сессии. False, если сессии нет."""
        session = self.peek(user_id)
        if session is None:
            logger.warning(f"Обновление сопоставления без сессии: пользователь {user_id}")
            return False
        session.speaker_mapping = new_mapping
        return True

    def take(self, user_id: int) -> Optional[MappingSession]:
        """Атомарно изъять сессию (подтверждение/пропуск): взял — владеешь.

        Повторный take возвращает None — двойной тап по «Подтвердить»
        не запускает второе возобновление.
        """
        self._evict_if_expired(user_id)
        self._timestamps.pop(user_id, None)
        return self._sessions.pop(user_id, None)

    def discard(self, user_id: int) -> None:
        """Выбросить сессию (UI не показался — пауза не состоялась)."""
        self._sessions.pop(user_id, None)
        self._timestamps.pop(user_id, None)


# Глобальный экземпляр
mapping_sessions = MappingSessionStore(ttl_seconds=3600)
