"""Сессия сопоставления: приостановленная обработка в ожидании подтверждения.

Типизированная замена dict-ам со строковыми ключами: хранилище in-memory,
поэтому объекты живут как есть — без model_dump()/регидрации. Атомарный
``take`` закрывает гонку двойного подтверждения: взял — владеешь, второй
тап получает None.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

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
    # Шаблон, выбранный в основном пути ДО паузы: возобновление берёт его как
    # есть, не выбирая заново (выбор шаблона — один раз, ADR-0003).
    template: Any = None
    # Спикеры с доставленным фрагментом записи: их цитата уже в подписи
    # фрагмента, карточка сопоставления её не дублирует (в т.ч. при перерисовках).
    speakers_with_audio: Set[str] = field(default_factory=set)
    # Сообщение-карточка сопоставления: ручной ввод имени перерисовывает её
    # на месте (сообщение пользователя с именем — отдельное сообщение чата).
    confirmation_message: Optional[Any] = None
    # Спикер, чей под-вид сейчас открыт и ждёт имя сообщением (None — под-вида
    # нет, ловец имени молчит). Признак «кто ждёт имя» живёт прямо в сессии
    # (#99): ставится при входе в под-вид (sm_change), снимается на «◀️ Назад»,
    # выборе участника, применении имени, подтверждении и пропуске.
    editing_speaker: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


class MappingSessionStore:
    """Хранилище сессий сопоставления по паре «пользователь + запись».

    Ключ — ``(user_id, session_key)``, где ``session_key`` это ``task_id``
    записи. Ключа по одному ``user_id`` не хватало: вторая загруженная встреча
    молча затирала первую вместе с её расшифровкой, а таймер первой доставлял
    вторую (критика v11). Теперь у каждой записи свой слот, и таймер забирает
    ровно свой.

    Карточка при этом по-прежнему одна: ``peek``/``take`` работают с активной
    (последней сохранённой) сессией пользователя — предыдущую при новой паузе
    доводит до протокола ``mapping_timeout.finish_superseded_session``.
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: Dict[Tuple[int, str], MappingSession] = {}
        self._timestamps: Dict[Tuple[int, str], datetime] = {}
        self._active: Dict[int, str] = {}
        # Когда у пользователя последний раз закрывалась сессия доставкой.
        # Нужно устаревшей карточке, чтобы отличать «работа пропала» от
        # «протокол уже доставлен» и не врать про потерю (критика v11).
        self._closed_at: Dict[int, datetime] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    @staticmethod
    def _key_of(session: MappingSession) -> str:
        """Ключ записи: task_id, а без него — стабильный суррогат объекта.

        ``task_id`` необязателен (быстрый путь его не заводит), но две
        безымянные записи всё равно обязаны занимать разные слоты. Атрибут
        читается через getattr: хранилищу достаточно объекта с сопоставлением,
        полный дата-класс оно не требует.
        """
        return getattr(session, "task_id", None) or f"anon:{id(session)}"

    def _forget(self, user_id: int, session_key: str) -> Optional[MappingSession]:
        """Снять запись со всех полок разом."""
        self._timestamps.pop((user_id, session_key), None)
        if self._active.get(user_id) == session_key:
            self._active.pop(user_id, None)
        return self._sessions.pop((user_id, session_key), None)

    def _evict_if_expired(self, user_id: int, session_key: str) -> None:
        timestamp = self._timestamps.get((user_id, session_key))
        if timestamp and datetime.now() - timestamp > self._ttl:
            logger.warning(
                f"Сессия сопоставления пользователя {user_id} "
                f"(запись {session_key}) истекла (старше {self._ttl})"
            )
            self._forget(user_id, session_key)

    def save(self, user_id: int, session: MappingSession) -> str:
        """Сохранить сессию при постановке обработки на паузу.

        Возвращает ключ записи: его получает таймер авто-доставки, чтобы
        забрать именно свою сессию, а не ту, что окажется активной к сроку.
        """
        session_key = self._key_of(session)
        self._sessions[(user_id, session_key)] = session
        self._timestamps[(user_id, session_key)] = datetime.now()
        self._active[user_id] = session_key
        logger.debug(
            f"Сессия сопоставления сохранена: пользователь {user_id}, "
            f"запись {session_key}"
        )
        return session_key

    def peek(self, user_id: int) -> Optional[MappingSession]:
        """Прочитать активную сессию, не изымая (для UI смены/выбора/отмены)."""
        session_key = self._active.get(user_id)
        if session_key is None:
            return None
        self._evict_if_expired(user_id, session_key)
        return self._sessions.get((user_id, session_key))

    def update_mapping(self, user_id: int, new_mapping: Dict[str, str]) -> bool:
        """Обновить сопоставление в активной сессии. False, если сессии нет."""
        session = self.peek(user_id)
        if session is None:
            logger.warning(f"Обновление сопоставления без сессии: пользователь {user_id}")
            return False
        session.speaker_mapping = new_mapping
        return True

    def take(self, user_id: int) -> Optional[MappingSession]:
        """Атомарно изъять активную сессию (подтверждение/пропуск).

        Повторный take возвращает None — двойной тап по «Подтвердить»
        не запускает второе возобновление.
        """
        session_key = self._active.get(user_id)
        if session_key is None:
            return None
        self._evict_if_expired(user_id, session_key)
        return self._closing(user_id, self._forget(user_id, session_key))

    def take_regardless(
        self, user_id: int, session_key: Optional[str] = None
    ) -> Optional[MappingSession]:
        """Изъять сессию, не проверяя TTL — для авто-доставки по таймауту.

        ``peek``/``take`` считают просроченную сессию мёртвой, и это правильно
        для карточки. Но внутри неё лежит готовая расшифровка — самая дорогая
        часть конвейера, и выбрасывать её нельзя: по таймауту обработка
        доводится до конца с тем сопоставлением, что успел ввести пользователь.

        ``session_key`` обязателен для таймера: без него берётся активная
        сессия, а таймер первой записи не имеет права забрать вторую.
        Атомарность та же, что у ``take``: успел пользователь подтвердить —
        таймер получит None и второй доставки не будет.
        """
        if session_key is None:
            session_key = self._active.get(user_id)
        if session_key is None:
            return None
        return self._closing(user_id, self._forget(user_id, session_key))

    def _closing(
        self, user_id: int, session: Optional[MappingSession]
    ) -> Optional[MappingSession]:
        """Отметить факт закрытия сессии доставкой (см. ``was_recently_closed``)."""
        if session is not None:
            self._closed_at[user_id] = datetime.now()
        return session

    def was_recently_closed(self, user_id: int) -> bool:
        """Была ли у пользователя сессия, закрытая доставкой, в пределах TTL.

        Устаревшая карточка спрашивает об этом, чтобы сказать правду: протокол
        доставлен и лежит выше в чате, а не «начните обработку заново».
        """
        closed_at = self._closed_at.get(user_id)
        return bool(closed_at and datetime.now() - closed_at <= self._ttl)

    @property
    def ttl_seconds(self) -> float:
        """TTL хранилища в секундах — таймер авто-доставки считает срок от него."""
        return self._ttl.total_seconds()

    def discard(self, user_id: int, session_key: Optional[str] = None) -> None:
        """Выбросить сессию (UI не показался — пауза не состоялась).

        Доставкой не считается: соврать устаревшей карточке про доставленный
        протокол здесь было бы хуже, чем промолчать.
        """
        if session_key is None:
            session_key = self._active.get(user_id)
        if session_key is not None:
            self._forget(user_id, session_key)


# Глобальный экземпляр
mapping_sessions = MappingSessionStore(ttl_seconds=3600)
