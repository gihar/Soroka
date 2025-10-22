"""
Тесты для извлечения информации о встрече из текста
"""

import unittest
import sys
import os

# Добавляем корневую директорию в path для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.meeting_info_service import meeting_info_service


class TestMeetingInfoExtraction(unittest.TestCase):
    """Тесты для извлечения информации о встрече"""

    def test_extract_from_email_format(self):
        """Тест извлечения из формата email"""
        email_text = """От: Тимченко Алексей Александрович
Кому: Носов Степан Евгеньевич; Поляков Михаил Андреевич
Копия: Прохоровская Оксана Александровна
Тема: Обсуждение требований к процессу
Когда: 22 октября 2025 г. 15:00-16:00."""

        meeting_info = meeting_info_service.extract_meeting_info(email_text)

        self.assertIsNotNone(meeting_info)
        self.assertEqual(meeting_info.topic, "Обсуждение требований к процессу")
        self.assertEqual(len(meeting_info.participants), 4)

        # Проверяем организатора
        organizer = next((p for p in meeting_info.participants if p.is_organizer), None)
        self.assertIsNotNone(organizer)
        self.assertEqual(organizer.name, "Тимченко Алексей Александрович")

        # Проверяем длительность
        self.assertEqual(meeting_info.duration_minutes, 60)

    def test_extract_from_simple_format(self):
        """Тест извлечения из простого формата"""
        simple_text = """Организатор: Иван Петров
Участники: Мария Иванова; Алексей Смирнов
Тема: Планирование проекта
Время: 14:00-15:30"""

        meeting_info = meeting_info_service.extract_meeting_info(simple_text)

        self.assertIsNotNone(meeting_info)
        self.assertEqual(meeting_info.topic, "Планирование проекта")
        self.assertEqual(len(meeting_info.participants), 3)

    def test_extract_date_time_parsing(self):
        """Тест парсинга даты и времени"""
        date_text = """Тема: Важная встреча
Когда: 25 октября 2025 г. 10:00-11:30."""

        meeting_info = meeting_info_service.extract_meeting_info(date_text)

        self.assertIsNotNone(meeting_info)
        self.assertEqual(meeting_info.duration_minutes, 90)

    def test_validation(self):
        """Тест валидации информации о встрече"""
        # Валидная информация
        meeting_info = meeting_info_service.extract_meeting_info(
            "От: Иван Петров\nКому: Мария Иванова\nТема: Тест\nКогда: 22 октября 2025 г. 15:00-16:00."
        )

        is_valid, error = meeting_info_service.validate_meeting_info(meeting_info)
        self.assertTrue(is_valid)

    def test_formatting_for_display(self):
        """Тест форматирования для отображения"""
        meeting_info = meeting_info_service.extract_meeting_info(
            "От: Иван Петров\nКому: Мария Иванова\nТема: Тестовая встреча\nКогда: 22 октября 2025 г. 15:00-16:00."
        )

        display_text = meeting_info_service.format_meeting_info_for_display(meeting_info)

        self.assertIn("Тестовая встреча", display_text)
        self.assertIn("Иван Петров", display_text)
        self.assertIn("Мария Иванова", display_text)


if __name__ == '__main__':
    unittest.main()
