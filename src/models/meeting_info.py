"""
Модели для извлечения информации о встрече
"""

from typing import List, Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class MeetingParticipant(BaseModel):
    """Информация об участнике встречи"""
    name: str = Field(..., description="Полное имя участника")
    role: Optional[str] = Field(None, description="Роль/должность")
    email: Optional[str] = Field(None, description="Email адрес")
    is_organizer: bool = Field(False, description="Организатор встречи")
    is_required: bool = Field(True, description="Обязательный участник")


class MeetingInfo(BaseModel):
    """Извлеченная информация о встрече"""
    topic: str = Field(..., description="Тема встречи")
    start_time: Optional[datetime] = Field(None, description="Время начала")
    end_time: Optional[datetime] = Field(None, description="Время окончания")
    duration_minutes: Optional[int] = Field(None, description="Длительность в минутах")
    participants: List[MeetingParticipant] = Field(default_factory=list, description="Список участников")
    organizer: Optional[str] = Field(None, description="Организатор встречи")
    location: Optional[str] = Field(None, description="Место проведения")
    description: Optional[str] = Field(None, description="Описание встречи")

    def get_participants_for_llm(self) -> List[Dict[str, str]]:
        """Получить участников в формате для LLM"""
        result = []
        for participant in self.participants:
            if participant.role:
                result.append({
                    "name": participant.name,
                    "role": participant.role
                })
            else:
                result.append({
                    "name": participant.name,
                    "role": ""
                })
        return result

    def get_formatted_participants(self) -> str:
        """Получить форматированное представление участников"""
        lines = []
        for participant in self.participants:
            if participant.role:
                lines.append(f"{participant.name}, {participant.role}")
            else:
                lines.append(participant.name)
        return "\n".join(lines)
