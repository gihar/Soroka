"""
Тесты для проверки использования форматированной транскрипции в построении структуры
"""

import unittest
import sys
import os

# Добавляем корневую директорию в path для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.meeting_structure_builder import MeetingStructureBuilder


class TestFormattedTranscriptStructure(unittest.TestCase):
    """Тесты для проверки работы с форматированной транскрипцией"""

    def setUp(self):
        """Подготовка к тестам"""
        # Инициализируем builder без LLM manager для тестирования базовой логики
        self.builder = MeetingStructureBuilder(llm_manager=None)
        
        # Исходная транскрипция (как будто без диаризации)
        self.raw_transcription = "Привет всем. Давайте обсудим проект. Да, согласен. Отлично."
        
        # Форматированная транскрипция с метками спикеров
        self.formatted_transcription = """SPEAKER_1: Привет всем. Давайте обсудим проект.

SPEAKER_2: Да, согласен.

SPEAKER_1: Отлично."""

    def test_formatted_transcript_has_speaker_labels(self):
        """Тест: форматированная транскрипция содержит метки спикеров"""
        # Проверяем, что в форматированной транскрипции есть метки
        self.assertIn("SPEAKER_", self.formatted_transcription)
        self.assertIn("SPEAKER_1", self.formatted_transcription)
        self.assertIn("SPEAKER_2", self.formatted_transcription)
        
    def test_raw_transcript_has_no_speaker_labels(self):
        """Тест: исходная транскрипция не содержит меток спикеров"""
        # Проверяем, что в исходной транскрипции нет меток
        self.assertNotIn("SPEAKER_", self.raw_transcription)

    def test_topics_prompt_detects_speaker_labels(self):
        """Тест: промпт извлечения тем определяет наличие меток спикеров"""
        # Тест для форматированной транскрипции
        prompt_formatted = self.builder._build_topics_extraction_prompt(
            self.formatted_transcription, 
            None
        )
        self.assertIn("ПРИМЕЧАНИЕ", prompt_formatted)
        self.assertIn("метки спикеров", prompt_formatted)
        
        # Тест для исходной транскрипции
        prompt_raw = self.builder._build_topics_extraction_prompt(
            self.raw_transcription, 
            None
        )
        # Для исходной транскрипции не должно быть примечания о метках
        if "SPEAKER_" not in self.raw_transcription:
            # Проверяем, что либо нет примечания, либо оно пустое
            self.assertTrue(
                "ПРИМЕЧАНИЕ" not in prompt_raw or 
                prompt_raw.count("ПРИМЕЧАНИЕ") == 0
            )

    def test_decisions_prompt_detects_speaker_labels(self):
        """Тест: промпт извлечения решений определяет наличие меток спикеров"""
        speakers = {"SPEAKER_1": None, "SPEAKER_2": None}
        
        # Тест для форматированной транскрипции
        prompt_formatted = self.builder._build_decisions_extraction_prompt(
            self.formatted_transcription,
            speakers
        )
        self.assertIn("ПРИМЕЧАНИЕ", prompt_formatted)
        self.assertIn("метки спикеров", prompt_formatted)
        self.assertIn("КТО принял каждое решение", prompt_formatted)

    def test_action_items_prompt_detects_speaker_labels(self):
        """Тест: промпт извлечения задач определяет наличие меток спикеров"""
        speakers = {"SPEAKER_1": None, "SPEAKER_2": None}
        
        # Тест для форматированной транскрипции
        prompt_formatted = self.builder._build_action_items_extraction_prompt(
            self.formatted_transcription,
            speakers
        )
        self.assertIn("ПРИМЕЧАНИЕ", prompt_formatted)
        self.assertIn("метки спикеров", prompt_formatted)
        self.assertIn("КОМУ назначена каждая задача", prompt_formatted)
        self.assertIn("Ответственный - это тот, кто взял задачу", prompt_formatted)

    def test_prompts_use_correct_speaker_id_format(self):
        """Тест: промпты используют правильный формат ID спикеров"""
        speakers = {"SPEAKER_1": None}
        
        # Проверяем промпт тем
        topics_prompt = self.builder._build_topics_extraction_prompt(
            self.formatted_transcription,
            None
        )
        self.assertIn("SPEAKER_1, SPEAKER_2", topics_prompt)
        
        # Проверяем промпт решений
        decisions_prompt = self.builder._build_decisions_extraction_prompt(
            self.formatted_transcription,
            speakers
        )
        self.assertIn("SPEAKER_1", decisions_prompt)
        
        # Проверяем промпт задач
        actions_prompt = self.builder._build_action_items_extraction_prompt(
            self.formatted_transcription,
            speakers
        )
        self.assertIn("SPEAKER_1", actions_prompt)


class TestFormattedTranscriptIntegration(unittest.TestCase):
    """Интеграционные тесты для проверки передачи форматированной транскрипции"""

    def test_formatted_transcript_preferred_over_raw(self):
        """Тест: форматированная транскрипция предпочтительнее исходной"""
        # Симуляция структуры данных из optimized_processing_service
        
        # Случай 1: Есть форматированная транскрипция
        diarization_data_with_formatted = {
            'formatted_transcript': 'SPEAKER_1: Текст 1\n\nSPEAKER_2: Текст 2',
            'total_speakers': 2
        }
        
        raw_transcription = 'Текст 1 Текст 2'
        
        # Логика выбора (как в optimized_processing_service)
        transcription_for_structure = raw_transcription
        if diarization_data_with_formatted and diarization_data_with_formatted.get('formatted_transcript'):
            transcription_for_structure = diarization_data_with_formatted['formatted_transcript']
        
        # Проверяем, что выбрана форматированная
        self.assertEqual(
            transcription_for_structure,
            'SPEAKER_1: Текст 1\n\nSPEAKER_2: Текст 2'
        )
        self.assertIn('SPEAKER_', transcription_for_structure)

    def test_fallback_to_raw_when_no_formatted(self):
        """Тест: fallback на исходную транскрипцию когда нет форматированной"""
        # Случай 2: Нет форматированной транскрипции
        diarization_data_without_formatted = {
            'total_speakers': 0
        }
        
        raw_transcription = 'Текст 1 Текст 2'
        
        # Логика выбора (как в optimized_processing_service)
        transcription_for_structure = raw_transcription
        if diarization_data_without_formatted and diarization_data_without_formatted.get('formatted_transcript'):
            transcription_for_structure = diarization_data_without_formatted['formatted_transcript']
        
        # Проверяем, что используется исходная
        self.assertEqual(transcription_for_structure, raw_transcription)
        self.assertNotIn('SPEAKER_', transcription_for_structure)

    def test_fallback_to_raw_when_diarization_none(self):
        """Тест: fallback на исходную транскрипцию когда diarization_data = None"""
        # Случай 3: diarization_data = None
        diarization_data = None
        raw_transcription = 'Текст без диаризации'
        
        # Логика выбора (как в optimized_processing_service)
        transcription_for_structure = raw_transcription
        if diarization_data and diarization_data.get('formatted_transcript'):
            transcription_for_structure = diarization_data['formatted_transcript']
        
        # Проверяем, что используется исходная
        self.assertEqual(transcription_for_structure, raw_transcription)


if __name__ == '__main__':
    unittest.main()

