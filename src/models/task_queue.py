"""
Модели для системы очереди задач
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from src.models.processing import ProcessingRequest


class TaskStatus(str, Enum):
    """Статус задачи в очереди"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskPriority(int, Enum):
    """Приоритет задачи"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    ADMIN = 3


@dataclass
class QueuedTask:
    """Задача в очереди на обработку"""
    
    task_id: UUID
    user_id: int
    chat_id: int
    request: ProcessingRequest
    message_id: Optional[int] = None
    status: TaskStatus = TaskStatus.QUEUED
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    position: int = 0  # Позиция в очереди (обновляется динамически)
    
    def __post_init__(self):
        """Конвертация строковых значений в enum после инициализации"""
        if isinstance(self.status, str):
            self.status = TaskStatus(self.status)
        if isinstance(self.priority, int) and not isinstance(self.priority, TaskPriority):
            # Находим соответствующий TaskPriority по значению
            for p in TaskPriority:
                if p.value == self.priority:
                    self.priority = p
                    break
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь для сохранения в БД"""
        import json
        
        return {
            "task_id": str(self.task_id),
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "file_id": self.request.file_id,
            "file_path": self.request.file_path,
            "file_name": self.request.file_name,
            "template_id": self.request.template_id,
            "llm_provider": self.request.llm_provider,
            "language": self.request.language,
            "is_external_file": self.request.is_external_file,
            # ДОБАВЛЕНО: Сохранение участников и информации о встрече
            "participants_list": json.dumps(self.request.participants_list) if self.request.participants_list else None,
            "meeting_topic": self.request.meeting_topic,
            "meeting_date": self.request.meeting_date,
            "meeting_time": self.request.meeting_time,
            "speaker_mapping": json.dumps(self.request.speaker_mapping) if self.request.speaker_mapping else None,
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": self.error_message
        }
    
    @classmethod
    def from_db_row(cls, row: dict) -> "QueuedTask":
        """Создать задачу из строки БД"""
        import json
        
        # ДОБАВЛЕНО: Восстановление участников и информации о встрече
        participants_list = None
        if row.get("participants_list"):
            try:
                participants_list = json.loads(row["participants_list"])
            except (json.JSONDecodeError, TypeError):
                participants_list = None
        
        speaker_mapping = None
        if row.get("speaker_mapping"):
            try:
                speaker_mapping = json.loads(row["speaker_mapping"])
            except (json.JSONDecodeError, TypeError):
                speaker_mapping = None
        
        # Восстанавливаем ProcessingRequest
        request = ProcessingRequest(
            file_id=row.get("file_id"),
            file_path=row.get("file_path"),
            file_name=row["file_name"],
            template_id=row["template_id"],
            llm_provider=row["llm_provider"],
            user_id=row["user_id"],
            language=row.get("language", "ru"),
            is_external_file=bool(row.get("is_external_file", False)),
            # ДОБАВЛЕНО: Восстановление участников и информации о встрече
            participants_list=participants_list,
            speaker_mapping=speaker_mapping,
            meeting_topic=row.get("meeting_topic"),
            meeting_date=row.get("meeting_date"),
            meeting_time=row.get("meeting_time")
        )
        
        return cls(
            task_id=UUID(row["task_id"]),
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            request=request,
            message_id=row.get("message_id"),
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row.get("priority", TaskPriority.NORMAL.value)),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row.get("started_at") else None,
            error_message=row.get("error_message")
        )

