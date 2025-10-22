"""
Тесты для функционала сопоставления участников
"""

import unittest
import sys
import os

# Добавляем корневую директорию в path для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.participants_service import participants_service
from src.utils.text_processing import replace_speakers_in_text


class TestParticipantsService(unittest.TestCase):
    """Тесты для ParticipantsService"""

    def test_parse_simple_participants(self):
        """Тест парсинга простого списка участников"""
        text = """Иван Петров, менеджер
Мария Иванова
Алексей Смирнов, разработчик"""

        participants = participants_service.parse_participants_text(text)

        self.assertEqual(len(participants), 3)
        self.assertEqual(participants[0]['name'], 'Иван Петров')
        self.assertEqual(participants[0]['role'], 'менеджер')
        self.assertEqual(participants[1]['name'], 'Мария Иванова')
        self.assertEqual(participants[1]['role'], '')
        self.assertEqual(participants[2]['name'], 'Алексей Смирнов')
        self.assertEqual(participants[2]['role'], 'разработчик')

    def test_parse_various_formats(self):
        """Тест парсинга различных форматов"""
        text = """Иван Петров - менеджер
Мария Иванова (разработчик)
Алексей Смирнов | тестировщик
Ольга Сидорова"""

        participants = participants_service.parse_participants_text(text)

        self.assertEqual(len(participants), 4)
        self.assertEqual(participants[0]['name'], 'Иван Петров')
        self.assertEqual(participants[0]['role'], 'менеджер')
        self.assertEqual(participants[1]['name'], 'Мария Иванова')
        self.assertEqual(participants[1]['role'], 'разработчик')
        self.assertEqual(participants[2]['name'], 'Алексей Смирнов')
        self.assertEqual(participants[2]['role'], 'тестировщик')
        self.assertEqual(participants[3]['name'], 'Ольга Сидорова')
        self.assertEqual(participants[3]['role'], '')

    def test_validation(self):
        """Тест валидации списка участников"""
        # Валидный список
        participants = [
            {'name': 'Иван Петров', 'role': 'менеджер'},
            {'name': 'Мария Иванова', 'role': ''}
        ]
        is_valid, error = participants_service.validate_participants(participants)
        self.assertTrue(is_valid)

        # Пустой список
        is_valid, error = participants_service.validate_participants([])
        self.assertFalse(is_valid)
        self.assertIn('пуст', error)

        # Слишком много участников
        big_list = [{'name': f'Участник {i}', 'role': ''} for i in range(25)]
        is_valid, error = participants_service.validate_participants(big_list)
        self.assertFalse(is_valid)
        self.assertIn('максимум', error)

        # Дубликаты
        participants_with_duplicates = [
            {'name': 'Иван Петров', 'role': 'менеджер'},
            {'name': 'Иван Петров', 'role': 'директор'}
        ]
        is_valid, error = participants_service.validate_participants(participants_with_duplicates)
        self.assertFalse(is_valid)
        self.assertIn('дубликаты', error)

    def test_formatting(self):
        """Тест форматирования для отображения"""
        participants = [
            {'name': 'Иван Петров', 'role': 'менеджер'},
            {'name': 'Мария Иванова', 'role': ''}
        ]

        display_text = participants_service.format_participants_for_display(participants)

        self.assertIn('Иван Петров', display_text)
        self.assertIn('менеджер', display_text)
        self.assertIn('Мария Иванова', display_text)


class TestTextProcessing(unittest.TestCase):
    """Тесты для утилит обработки текста"""

    def test_replace_speakers_basic(self):
        """Тест базовой замены спикеров"""
        text = """SPEAKER_1: Добрый день, команда
Спикер 2: Привет всем
SPEAKER_3: Как дела?
Ответственный: Спикер 1"""

        mapping = {
            'SPEAKER_1': 'Иван Петров',
            'SPEAKER_2': 'Мария Иванова',
            'SPEAKER_3': 'Алексей Смирнов'
        }

        result = replace_speakers_in_text(text, mapping)

        self.assertIn('Иван Петров', result)
        self.assertIn('Мария Иванова', result)
        self.assertIn('Алексей Смирнов', result)
        self.assertNotIn('SPEAKER_1', result)
        self.assertNotIn('Спикер 2', result)

    def test_replace_speakers_with_numbers(self):
        """Тест замены с номерами"""
        text = """Участники: Спикер 1; Спикер 2; Спикер 10
Решения: Спикер 1 утвердил план"""

        mapping = {
            'SPEAKER_1': 'Иван Петров',
            'SPEAKER_2': 'Мария Иванова',
            'SPEAKER_10': 'Алексей Смирнов'
        }

        result = replace_speakers_in_text(text, mapping)

        self.assertIn('Иван Петров', result)
        self.assertIn('Мария Иванова', result)
        self.assertIn('Алексей Смирнов', result)
        # Проверяем что правильно заменился Спикер 10, а не Спикер 1
        self.assertNotIn('Спикер 10', result)


if __name__ == '__main__':
    unittest.main()
