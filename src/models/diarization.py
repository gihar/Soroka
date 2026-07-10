"""
Типизированная «Диаризация» — единый value object, который строят все источники.

Хранит ТОЛЬКО последовательность сегментов; список спикеров, тексты по спикерам,
форматированную транскрипцию и сводку модель выводит из сегментов как свойства.
Потребители читают эти свойства напрямую — промежуточной dict-формы нет.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel

from src.utils.transcript_formatter import format_transcript_with_speaker_sequence


class Segment(BaseModel):
    """Сегмент диаризации: реплика одного спикера с опциональными таймингами."""

    speaker: str
    text: str
    start: Optional[float] = None  # тайминги нужны фрагментам записи
    end: Optional[float] = None


class Diarization(BaseModel):
    """Диаризация: последовательность сегментов и производные представления."""

    segments: List[Segment]

    @property
    def speakers(self) -> List[str]:
        """Уникальные спикеры в порядке их появления в сегментах."""
        ordered: List[str] = []
        for segment in self.segments:
            if segment.speaker not in ordered:
                ordered.append(segment.speaker)
        return ordered

    @property
    def speakers_text(self) -> Dict[str, str]:
        """Текст каждого спикера, склеенный по порядку; пустые реплики пропускаются."""
        pieces: Dict[str, List[str]] = {}
        for segment in self.segments:
            pieces.setdefault(segment.speaker, [])
            text = segment.text.strip()
            if text:
                pieces[segment.speaker].append(text)
        return {speaker: " ".join(texts) for speaker, texts in pieces.items()}

    @property
    def formatted_transcript(self) -> str:
        """Форматированная транскрипция с сохранением чередования реплик."""
        return format_transcript_with_speaker_sequence(
            [segment.model_dump() for segment in self.segments]
        )

    @property
    def speakers_summary(self) -> str:
        """Сводка: общее число спикеров и количество слов у каждого построчно."""
        speakers = self.speakers
        speakers_text = self.speakers_text
        summary = f"Общее количество говорящих: {len(speakers)}\n\n"
        for speaker in speakers:
            word_count = len(speakers_text.get(speaker, "").split())
            summary += f"{speaker}: {word_count} слов\n"
        return summary
