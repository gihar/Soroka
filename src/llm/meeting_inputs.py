"""Входные данные встречи — всё, что генерация протокола знает о встрече помимо записи.

Один неизменяемый объект вместо россыпи именованных аргументов генератора: поля
встречи едут одним экземпляром, а представления для промпта вычисляются здесь, а
не у каждого вызывающего.

Тема, дата и время встречи сюда не входят намеренно: ни один промпт их не читает
(характеризация до рефакторинга это подтвердила — ``meeting_metadata`` уходил в
``build_analysis_prompt`` и игнорировался). Дата протокола достраивается
детерминированным фолбэком после генерации из самого запроса.
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from src.services.participants_service import participants_service


@dataclass(frozen=True)
class MeetingInputs:
    """Входные данные встречи для генерации протокола (неизменяемые)."""

    participants: Tuple[Mapping[str, str], ...] = ()
    agenda: Optional[str] = None
    projects: Optional[str] = None
    speaker_mapping: Optional[Mapping[str, str]] = None
    meeting_type: Optional[str] = None

    @classmethod
    def from_request(cls, request: Any, *, meeting_type: Optional[str] = None) -> "MeetingInputs":
        """Собрать из запроса на обработку; тип встречи приходит отдельно — от вызывающего.

        Изменяемые части запроса копируются: правка запроса после сборки объект
        не задевает.
        """
        mapping = request.speaker_mapping
        return cls(
            participants=tuple(
                MappingProxyType(dict(participant))
                for participant in request.participants_list or ()
            ),
            agenda=request.meeting_agenda,
            projects=request.project_list,
            speaker_mapping=MappingProxyType(dict(mapping)) if mapping is not None else None,
            meeting_type=meeting_type,
        )

    @property
    def analysis_settled(self) -> bool:
        """Итоги ЭТАПА 1 уже известны — и тип встречи, и сопоставление спикеров.

        Одного из двух мало: сопоставление без типа (или тип без сопоставления)
        анализ не отменяет, и тогда его вердикт побеждает переданное.
        """
        return bool(self.meeting_type and self.speaker_mapping)

    def participants_for_prompt(self) -> str:
        """Список участников для промпта анализа: «- Имя Фамилия (роль)» построчно.

        Участников нет — модель видит «Не предоставлен», а не пустое место.
        """
        if not self.participants:
            return "Не предоставлен"
        return participants_service.format_participants_for_llm(self.participants)


# Встреча, о которой не известно ничего: участников, повестки, проектов,
# сопоставления и типа нет. Объект неизменяем, поэтому один на всех.
NO_MEETING_INPUTS = MeetingInputs()
