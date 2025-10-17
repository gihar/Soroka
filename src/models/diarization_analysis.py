"""
Модели данных для анализа диаризации
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class SpeakerRole(str, Enum):
    """Роли спикеров во встрече"""
    MODERATOR = "moderator"  # Модератор/ведущий
    DOMINANT = "dominant"    # Доминирующий участник
    EXPERT = "expert"        # Эксперт/специалист
    PARTICIPANT = "participant"  # Обычный участник
    OBSERVER = "observer"    # Наблюдатель (редко говорит)
    UNKNOWN = "unknown"      # Роль не определена


@dataclass
class SpeakerContribution:
    """Вклад отдельного спикера во встречу"""
    speaker_id: str
    total_speaking_time: float  # В секундах
    speaking_time_percent: float  # Процент от общего времени
    word_count: int
    turn_count: int  # Количество реплик
    average_turn_duration: float  # Средняя длительность реплики
    interruptions: int  # Количество прерываний
    interrupted_by: List[str] = field(default_factory=list)  # Кем был прерван
    role: SpeakerRole = SpeakerRole.UNKNOWN


@dataclass
class InteractionPattern:
    """Паттерн взаимодействия между спикерами"""
    speaker_a: str
    speaker_b: str
    turn_exchanges: int  # Количество обменов репликами
    avg_response_time: float  # Среднее время ответа
    interaction_score: float  # Оценка интенсивности взаимодействия (0-1)
    topics_discussed: List[str] = field(default_factory=list)


@dataclass
class MeetingPhase:
    """Фаза встречи (временной сегмент)"""
    phase_id: int
    start_time: float
    end_time: float
    duration: float
    dominant_speaker: Optional[str]
    participants: List[str]
    topics: List[str] = field(default_factory=list)
    phase_type: str = "discussion"  # discussion, presentation, q&a, decision


@dataclass
class TopicSegment:
    """Сегмент обсуждения определенной темы"""
    topic_id: int
    topic_summary: str
    start_time: float
    end_time: float
    speakers_involved: List[str]
    key_points: List[str] = field(default_factory=list)


@dataclass
class DiarizationAnalysisResult:
    """Результат полного анализа диаризации"""
    # Вклад спикеров
    speakers: Dict[str, SpeakerContribution]
    
    # Паттерны взаимодействия
    interactions: List[InteractionPattern]
    
    # Фазы встречи
    phases: List[MeetingPhase]
    
    # Тематические сегменты
    topic_segments: List[TopicSegment]
    
    # Общая статистика
    total_duration: float
    total_speakers: int
    dominant_speaker_id: Optional[str]
    most_active_interactions: List[Tuple[str, str]]  # Пары наиболее активно взаимодействующих
    
    # Метаинформация
    meeting_type: str = "general"  # general, presentation, discussion, brainstorm
    energy_level: str = "medium"  # low, medium, high
    participation_balance: float = 0.5  # 0 = очень несбалансированно, 1 = идеально сбалансировано
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь для передачи в LLM"""
        return {
            "speakers": {
                speaker_id: {
                    "speaking_time_percent": contrib.speaking_time_percent,
                    "word_count": contrib.word_count,
                    "turn_count": contrib.turn_count,
                    "role": contrib.role.value,
                    "average_turn_duration": contrib.average_turn_duration
                }
                for speaker_id, contrib in self.speakers.items()
            },
            "interactions": [
                {
                    "speaker_a": i.speaker_a,
                    "speaker_b": i.speaker_b,
                    "exchanges": i.turn_exchanges,
                    "score": i.interaction_score
                }
                for i in self.interactions[:5]  # Топ-5 взаимодействий
            ],
            "phases": [
                {
                    "phase_id": p.phase_id,
                    "duration": p.duration,
                    "dominant_speaker": p.dominant_speaker,
                    "phase_type": p.phase_type
                }
                for p in self.phases
            ],
            "statistics": {
                "total_duration": self.total_duration,
                "total_speakers": self.total_speakers,
                "dominant_speaker": self.dominant_speaker_id,
                "meeting_type": self.meeting_type,
                "energy_level": self.energy_level,
                "participation_balance": self.participation_balance
            }
        }
    
    def get_enriched_summary(self) -> str:
        """Получить обогащенное текстовое описание для LLM"""
        lines = []
        
        lines.append("=== ДЕТАЛЬНЫЙ АНАЛИЗ УЧАСТНИКОВ ===\n")
        
        # Сортируем спикеров по времени говорения
        sorted_speakers = sorted(
            self.speakers.items(),
            key=lambda x: x[1].speaking_time_percent,
            reverse=True
        )
        
        for speaker_id, contrib in sorted_speakers:
            role_desc = {
                SpeakerRole.MODERATOR: "Модератор/Ведущий",
                SpeakerRole.DOMINANT: "Доминирующий участник",
                SpeakerRole.EXPERT: "Эксперт",
                SpeakerRole.PARTICIPANT: "Участник",
                SpeakerRole.OBSERVER: "Наблюдатель"
            }.get(contrib.role, "Участник")
            
            lines.append(
                f"{speaker_id} ({role_desc}):\n"
                f"  - Время говорения: {contrib.speaking_time_percent:.1f}%\n"
                f"  - Количество слов: {contrib.word_count}\n"
                f"  - Количество реплик: {contrib.turn_count}\n"
                f"  - Средняя длительность реплики: {contrib.average_turn_duration:.1f}с\n"
            )
        
        lines.append("\n=== ПАТТЕРНЫ ВЗАИМОДЕЙСТВИЯ ===\n")
        
        # Топ-3 взаимодействия
        top_interactions = sorted(
            self.interactions,
            key=lambda x: x.interaction_score,
            reverse=True
        )[:3]
        
        for interaction in top_interactions:
            lines.append(
                f"{interaction.speaker_a} <-> {interaction.speaker_b}: "
                f"{interaction.turn_exchanges} обменов, "
                f"интенсивность {interaction.interaction_score:.2f}\n"
            )
        
        lines.append("\n=== ДИНАМИКА ВСТРЕЧИ ===\n")
        lines.append(f"Тип встречи: {self.meeting_type}\n")
        lines.append(f"Уровень энергии: {self.energy_level}\n")
        lines.append(f"Баланс участия: {self.participation_balance:.2f}\n")
        
        if self.phases:
            lines.append(f"\nВстреча состояла из {len(self.phases)} фаз:\n")
            for phase in self.phases:
                lines.append(
                    f"  - Фаза {phase.phase_id} ({phase.phase_type}): "
                    f"{phase.duration:.1f}с, ведущий: {phase.dominant_speaker}\n"
                )
        
        return ''.join(lines)


@dataclass
class ValidationResult:
    """Результат валидации протокола"""
    is_valid: bool
    completeness_score: float  # 0-1
    structure_score: float  # 0-1
    factual_accuracy_score: float  # 0-1
    diarization_usage_score: float  # 0-1
    overall_score: float  # 0-1
    
    missing_fields: List[str] = field(default_factory=list)
    empty_fields: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь"""
        return {
            "is_valid": self.is_valid,
            "scores": {
                "completeness": self.completeness_score,
                "structure": self.structure_score,
                "factual_accuracy": self.factual_accuracy_score,
                "diarization_usage": self.diarization_usage_score,
                "overall": self.overall_score
            },
            "issues": {
                "missing_fields": self.missing_fields,
                "empty_fields": self.empty_fields
            },
            "warnings": self.warnings,
            "suggestions": self.suggestions
        }

