"""
Структурированные модели данных для встреч
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class DecisionPriority(str, Enum):
    """Приоритет решения"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionItemStatus(str, Enum):
    """Статус задачи"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ActionItemPriority(str, Enum):
    """Приоритет задачи"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Decision(BaseModel):
    """Структура для хранения решения"""
    id: str = Field(..., description="Уникальный ID решения")
    text: str = Field(..., description="Текст решения")
    context: str = Field("", description="Контекст принятия решения")
    decision_makers: List[str] = Field(default_factory=list, description="ID спикеров, принявших решение")
    mentioned_speakers: List[str] = Field(default_factory=list, description="Упомянутые спикеры")
    priority: DecisionPriority = Field(DecisionPriority.MEDIUM, description="Важность решения")
    timestamp: Optional[float] = Field(None, description="Временная метка в секундах")
    related_topics: List[str] = Field(default_factory=list, description="ID связанных тем")
    
    class Config:
        use_enum_values = True


class ActionItem(BaseModel):
    """Структура для задачи/поручения"""
    id: str = Field(..., description="Уникальный ID задачи")
    description: str = Field(..., description="Описание задачи")
    assignee: Optional[str] = Field(None, description="ID ответственного спикера")
    assignee_name: Optional[str] = Field(None, description="Имя ответственного (если извлечено)")
    deadline: Optional[str] = Field(None, description="Срок выполнения")
    priority: ActionItemPriority = Field(ActionItemPriority.MEDIUM, description="Приоритет задачи")
    status: ActionItemStatus = Field(ActionItemStatus.NOT_STARTED, description="Статус выполнения")
    related_decisions: List[str] = Field(default_factory=list, description="ID связанных решений")
    related_topics: List[str] = Field(default_factory=list, description="ID связанных тем")
    context: str = Field("", description="Контекст задачи")
    timestamp: Optional[float] = Field(None, description="Временная метка в секундах")
    
    class Config:
        use_enum_values = True


class Topic(BaseModel):
    """Структура для темы обсуждения"""
    id: str = Field(..., description="Уникальный ID темы")
    title: str = Field(..., description="Название темы")
    description: str = Field("", description="Описание темы")
    start_time: Optional[float] = Field(None, description="Начало обсуждения (секунды)")
    end_time: Optional[float] = Field(None, description="Конец обсуждения (секунды)")
    duration: Optional[float] = Field(None, description="Длительность обсуждения")
    participants: List[str] = Field(default_factory=list, description="ID участников обсуждения")
    key_points: List[str] = Field(default_factory=list, description="Ключевые моменты")
    related_decisions: List[str] = Field(default_factory=list, description="ID связанных решений")
    related_actions: List[str] = Field(default_factory=list, description="ID связанных задач")
    sentiment: Optional[str] = Field(None, description="Общий тон обсуждения")


class SpeakerProfile(BaseModel):
    """Расширенный профиль спикера"""
    speaker_id: str = Field(..., description="ID спикера")
    inferred_name: Optional[str] = Field(None, description="Предполагаемое имя")
    role: Optional[str] = Field(None, description="Роль спикера")
    speaking_time_percent: float = Field(0.0, description="Процент времени говорения")
    word_count: int = Field(0, description="Количество слов")
    decisions_made: List[str] = Field(default_factory=list, description="ID принятых решений")
    tasks_assigned: List[str] = Field(default_factory=list, description="ID назначенных задач")
    key_quotes: List[str] = Field(default_factory=list, description="Ключевые цитаты")
    topics_discussed: List[str] = Field(default_factory=list, description="ID обсуждаемых тем")
    interaction_count: int = Field(0, description="Количество взаимодействий с другими")
    
    def to_summary(self) -> str:
        """Краткое описание профиля"""
        parts = [f"{self.speaker_id}"]
        if self.inferred_name:
            parts.append(f"({self.inferred_name})")
        if self.role:
            parts.append(f"- {self.role}")
        parts.append(f"{self.speaking_time_percent:.1f}% времени")
        return " ".join(parts)


class MeetingMetadata(BaseModel):
    """Метаданные встречи"""
    meeting_date: Optional[str] = Field(None, description="Дата встречи")
    meeting_time: Optional[str] = Field(None, description="Время встречи")
    duration_seconds: float = Field(0.0, description="Длительность в секундах")
    duration_formatted: str = Field("", description="Длительность в читаемом формате")
    participant_count: int = Field(0, description="Количество участников")
    meeting_type: str = Field("general", description="Тип встречи")
    language: str = Field("ru", description="Язык")
    transcription_quality: Optional[float] = Field(None, description="Оценка качества транскрипции (0-1)")
    has_diarization: bool = Field(False, description="Есть ли диаризация")
    processing_timestamp: datetime = Field(default_factory=datetime.now, description="Время обработки")


class MeetingStructure(BaseModel):
    """Основная структура встречи"""
    # Метаданные
    metadata: MeetingMetadata = Field(..., description="Метаданные встречи")
    
    # Основные сущности
    speakers: Dict[str, SpeakerProfile] = Field(default_factory=dict, description="Профили спикеров")
    topics: List[Topic] = Field(default_factory=list, description="Темы обсуждения")
    decisions: List[Decision] = Field(default_factory=list, description="Принятые решения")
    action_items: List[ActionItem] = Field(default_factory=list, description="Задачи и поручения")
    
    # Исходные данные
    original_transcription: str = Field("", description="Исходная транскрипция")
    diarization_available: bool = Field(False, description="Доступна ли диаризация")
    
    # Аналитика
    key_insights: List[str] = Field(default_factory=list, description="Ключевые инсайты")
    summary: str = Field("", description="Краткое резюме встречи")
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для передачи в LLM"""
        return {
            "metadata": self.metadata.model_dump(),
            "speakers": {
                speaker_id: {
                    "id": profile.speaker_id,
                    "name": profile.inferred_name,
                    "role": profile.role,
                    "speaking_time_percent": profile.speaking_time_percent,
                    "word_count": profile.word_count,
                    "decisions_count": len(profile.decisions_made),
                    "tasks_count": len(profile.tasks_assigned)
                }
                for speaker_id, profile in self.speakers.items()
            },
            "topics": [
                {
                    "id": topic.id,
                    "title": topic.title,
                    "description": topic.description,
                    "duration": topic.duration,
                    "participants": topic.participants,
                    "key_points": topic.key_points
                }
                for topic in self.topics
            ],
            "decisions": [
                {
                    "id": decision.id,
                    "text": decision.text,
                    "context": decision.context,
                    "decision_makers": decision.decision_makers,
                    "priority": decision.priority
                }
                for decision in self.decisions
            ],
            "action_items": [
                {
                    "id": action.id,
                    "description": action.description,
                    "assignee": action.assignee,
                    "assignee_name": action.assignee_name,
                    "deadline": action.deadline,
                    "priority": action.priority,
                    "status": action.status
                }
                for action in self.action_items
            ],
            "statistics": {
                "total_speakers": len(self.speakers),
                "total_topics": len(self.topics),
                "total_decisions": len(self.decisions),
                "total_actions": len(self.action_items),
                "duration": self.metadata.duration_formatted
            }
        }
    
    def get_structured_summary(self) -> str:
        """Получить структурированное текстовое описание"""
        lines = []
        
        lines.append("=== СТРУКТУРА ВСТРЕЧИ ===\n")
        
        # Метаданные
        lines.append(f"Тип: {self.metadata.meeting_type}")
        lines.append(f"Длительность: {self.metadata.duration_formatted}")
        lines.append(f"Участников: {self.metadata.participant_count}\n")
        
        # Спикеры
        if self.speakers:
            lines.append("УЧАСТНИКИ:")
            for speaker_id, profile in self.speakers.items():
                lines.append(f"- {profile.to_summary()}")
            lines.append("")
        
        # Темы
        if self.topics:
            lines.append(f"ТЕМЫ ОБСУЖДЕНИЯ ({len(self.topics)}):")
            for topic in self.topics:
                lines.append(f"- {topic.title}")
                if topic.key_points:
                    for point in topic.key_points[:3]:
                        lines.append(f"  • {point}")
            lines.append("")
        
        # Решения
        if self.decisions:
            lines.append(f"РЕШЕНИЯ ({len(self.decisions)}):")
            for decision in self.decisions:
                priority_mark = "❗" if decision.priority == DecisionPriority.HIGH else ""
                lines.append(f"- {priority_mark}{decision.text}")
            lines.append("")
        
        # Задачи
        if self.action_items:
            lines.append(f"ЗАДАЧИ ({len(self.action_items)}):")
            for action in self.action_items:
                assignee_info = f" → {action.assignee_name or action.assignee}" if action.assignee else ""
                priority_mark = "🔴" if action.priority == ActionItemPriority.CRITICAL else ""
                lines.append(f"- {priority_mark}{action.description}{assignee_info}")
            lines.append("")
        
        return "\n".join(lines)
    
    def validate_structure(self) -> Dict[str, Any]:
        """Валидация структуры данных"""
        issues = []
        warnings = []
        
        # Проверка спикеров
        if not self.speakers:
            warnings.append("Нет информации о спикерах")
        
        # Проверка решений
        for decision in self.decisions:
            if not decision.text.strip():
                issues.append(f"Решение {decision.id} имеет пустой текст")
            if not decision.decision_makers and not decision.mentioned_speakers:
                warnings.append(f"Решение {decision.id} не привязано ни к одному спикеру")
        
        # Проверка задач
        for action in self.action_items:
            if not action.description.strip():
                issues.append(f"Задача {action.id} имеет пустое описание")
            if not action.assignee:
                warnings.append(f"Задача {action.id} не имеет ответственного")
        
        # Проверка тем
        for topic in self.topics:
            if not topic.title.strip():
                issues.append(f"Тема {topic.id} имеет пустое название")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "statistics": {
                "speakers_count": len(self.speakers),
                "topics_count": len(self.topics),
                "decisions_count": len(self.decisions),
                "actions_count": len(self.action_items)
            }
        }

