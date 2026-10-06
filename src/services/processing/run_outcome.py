"""Исход прогона — чем закончился прогон конвейера для вызывающего.

Раньше пауза на карточке сопоставления сообщалась вызывающему значением
``None`` вместо результата: воркер проверял ``result is None`` и по нему решал,
гасить ли трекер. Теперь исход явный — готов (с результатом) или приостановлен
(обработку доведёт закрытие паузы, ADR-0011).
"""

from dataclasses import dataclass
from typing import Optional

from src.models.processing import ProcessingResult


@dataclass(frozen=True)
class RunOutcome:
    """Исход прогона: ``result`` есть только у готового прогона."""

    result: Optional[ProcessingResult] = None
    paused: bool = False

    @classmethod
    def ready(cls, result: ProcessingResult) -> "RunOutcome":
        """Протокол собран и доставлен (или доставка не удалась) хвостом."""
        return cls(result=result, paused=False)

    @classmethod
    def paused_on_card(cls) -> "RunOutcome":
        """Прогон встал на карточке сопоставления; дальше его ведёт пауза."""
        return cls(result=None, paused=True)
