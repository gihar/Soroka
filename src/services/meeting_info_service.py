"""
Сервис для извлечения информации о встрече из текста
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from loguru import logger

from src.models.meeting_info import MeetingInfo, MeetingParticipant


class MeetingInfoService:
    """Сервис для извлечения информации о встрече из текста"""

    def __init__(self):
        # Паттерны для различных форматов
        self.patterns = {
            'email_from': r'От:\s*(.+?)(?:\n|$)',
            'email_to': r'(?:Кому|Копия|To):\s*(.+?)(?:\n|$)',
            'email_subject': r'(?:Тема|Subject):\s*(.+?)(?:\n|$)',
            'email_when': r'(?:Когда|When):\s*(.+?)(?:\n|$)',

            # Альтернативные форматы
            'participants_from': r'(?:Организатор|От|From):\s*(.+?)(?:\n|$)',
            'participants_to': r'(?:Участники|Кому|To):\s*(.+?)(?:\n|$)',
            'participants_cc': r'(?:Копия|Cc):\s*(.+?)(?:\n|$)',
            'meeting_topic': r'(?:Тема|Subject|Повестка|Agenda):\s*(.+?)(?:\n|$)',
            'meeting_time': r'(?:Время|When|Time):\s*(.+?)(?:\n|$)',
            'meeting_date': r'(?:Дата|When|Date):\s*(.+?)(?:\n|$)',

            # Общие паттерны времени
            'time_range': r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})',
            'single_time': r'(\d{1,2}):(\d{2})',
            'full_date_time': r'(\d{1,2})\s+([а-яА-Я]+)\s+(\d{4})?\s*г?\.?\s*(\d{1,2}):(\d{2})',
        }

        # Месяцы для парсинга
        self.months = {
            'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4, 'май': 5, 'июнь': 6,
            'июль': 7, 'август': 8, 'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12,
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
            'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
            'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
            'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
        }

    def extract_meeting_info(self, text: str) -> Optional[MeetingInfo]:
        """
        Извлечь информацию о встрече из текста

        Args:
            text: Текст с информацией о встрече

        Returns:
            MeetingInfo или None если не удалось извлечь
        """
        try:
            logger.info(f"Извлечение информации о встрече из текста длиной {len(text)} символов")

            # Извлекаем участников
            participants = self._extract_participants(text)

            # Извлекаем тему
            topic = self._extract_topic(text)

            # Извлекаем дату и время
            date_time_info = self._extract_date_time(text)

            # Создаем MeetingInfo
            meeting_info = MeetingInfo(
                topic=topic or "Не указана",
                participants=participants,
                **date_time_info
            )

            # Определяем организатора
            organizer = self._extract_organizer(text)
            if organizer:
                meeting_info.organizer = organizer
                # Помечаем организатора в списке участников
                for participant in meeting_info.participants:
                    if participant.name == organizer:
                        participant.is_organizer = True
                        break

            logger.info(f"Извлечена информация: {len(participants)} участников, тема: {topic}")
            return meeting_info

        except Exception as e:
            logger.error(f"Ошибка при извлечении информации о встрече: {e}")
            return None

    def _extract_participants(self, text: str) -> List[MeetingParticipant]:
        """Извлечь список участников из текста"""
        participants = []

        # Извлекаем из поля "От"
        organizer_match = self._find_pattern(text, 'email_from') or self._find_pattern(text, 'participants_from')
        if organizer_match:
            organizer_names = self._extract_name_from_email_line(organizer_match)
            # Обычно организатор один, берем первое имя
            if organizer_names:
                participants.append(MeetingParticipant(
                    name=organizer_names[0],
                    is_organizer=True,
                    is_required=True
                ))

        # Извлекаем из поля "Кому"
        to_match = self._find_pattern(text, 'email_to') or self._find_pattern(text, 'participants_to')
        if to_match:
            names = self._extract_names_from_list(to_match)
            for name in names:
                if name and name not in [p.name for p in participants]:
                    participants.append(MeetingParticipant(
                        name=name,
                        is_required=True
                    ))

        # Извлекаем из поля "Копия"
        cc_match = self._find_pattern(text, 'participants_cc')
        if cc_match:
            names = self._extract_names_from_list(cc_match)
            for name in names:
                if name and name not in [p.name for p in participants]:
                    participants.append(MeetingParticipant(
                        name=name,
                        is_required=False  # Участники в копии не обязательны
                    ))

        # Дополнительно парсим все строки как потенциальных участников
        # если не нашли участников в email-полях
        if not participants:
            participants = self._parse_text_as_participants_list(text)

        return participants

    def _parse_text_as_participants_list(self, text: str) -> List[MeetingParticipant]:
        """Парсинг текста как обычного списка участников"""
        participants = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Пропускаем строки, которые выглядят как email-поля
            if any(line.lower().startswith(prefix) for prefix in ['от:', 'кому:', 'копия:', 'тема:', 'когда:', 'дата:', 'время:']):
                continue
                
            participant = self._parse_single_participant_line(line)
            if participant:
                participants.append(participant)
        
        return participants

    def _parse_single_participant_line(self, line: str) -> Optional[MeetingParticipant]:
        """Парсинг одной строки с участником"""
        # Убираем номера списков в начале (1., 2., -, •, etc)
        line = re.sub(r'^[\d\-•*]+[\.\)]\s*', '', line).strip()
        
        if not line:
            return None
        
        # Паттерны для извлечения имени и роли
        patterns = [
            # "Иван Петров, менеджер"
            r'^(.+?)\s*,\s*(.+)$',
            # "Иван Петров - менеджер"
            r'^(.+?)\s*-\s*(.+)$',
            # "Иван Петров (менеджер)"
            r'^(.+?)\s*\((.+?)\)\s*$',
            # "Иван Петров | менеджер"
            r'^(.+?)\s*\|\s*(.+)$',
        ]
        
        name = ""
        role = ""
        
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                name = match.group(1).strip()
                role = match.group(2).strip()
                break
        
        # Если не удалось распарсить с ролью, берем всю строку как имя
        if not name:
            if len(line) >= 2:
                name = line
                role = ""
        
        # Возвращаем только если есть имя
        if name and len(name) >= 2:
            return MeetingParticipant(
                name=name,
                role=role,
                is_required=True
            )
        
        return None

    def _extract_topic(self, text: str) -> Optional[str]:
        """Извлечь тему встречи"""
        patterns = ['email_subject', 'meeting_topic']
        for pattern_name in patterns:
            match = self._find_pattern(text, pattern_name)
            if match:
                return match.strip()
        return None

    def _extract_date_time(self, text: str) -> Dict:
        """Извлечь дату и время встречи"""
        result = {}

        # Ищем полную информацию о времени
        when_match = self._find_pattern(text, 'email_when') or self._find_pattern(text, 'meeting_time')
        if when_match:
            # Парсим формат "22 октября 2025 г. 15:00-16:00"
            date_time_info = self._parse_date_time_string(when_match)
            if date_time_info:
                result.update(date_time_info)

        # Если не нашли полную информацию, ищем отдельно
        if 'start_time' not in result:
            # Ищем дату
            date_match = self._find_pattern(text, 'meeting_date')
            if date_match:
                parsed_date = self._parse_date_string(date_match)
                if parsed_date:
                    result['start_time'] = parsed_date

        return result

    def _extract_organizer(self, text: str) -> Optional[str]:
        """Извлечь организатора встречи"""
        organizer_match = self._find_pattern(text, 'email_from') or self._find_pattern(text, 'participants_from')
        if organizer_match:
            names = self._extract_name_from_email_line(organizer_match)
            # Возвращаем первое имя из списка как организатора
            return names[0] if names else None
        return None

    def _find_pattern(self, text: str, pattern_name: str) -> Optional[str]:
        """Найти совпадение по паттерну"""
        if pattern_name not in self.patterns:
            return None

        pattern = self.patterns[pattern_name]
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)

        if match:
            # Для многострочных паттернов берем только первую группу
            if pattern_name in ['email_to', 'participants_cc', 'email_when',
                                'email_subject', 'meeting_topic']:
                return match.group(1).strip()
            else:
                return match.group(0).replace(f'{pattern_name.split("_")[0]}:', '').strip()

        return None

    def _escape_markdown(self, text: str) -> str:
        """Экранирование специальных символов Markdown"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text

    def _extract_name_from_email_line(self, line: str) -> List[str]:
        """Извлечь все имена из строки (может содержать несколько ФИО через запятую)
        
        Args:
            line: Строка с одним или несколькими ФИО
            
        Returns:
            Список извлеченных имен
        """
        # Убираем email если есть
        line = re.sub(r'<[^>]+>', '', line)

        # Ищем ВСЕ полные имена (3 слова: Фамилия Имя Отчество)
        name_matches = re.findall(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)', line)
        if name_matches:
            return [name.strip() for name in name_matches]

        # Если не нашли полные имена, берем первые 2-3 слова как одно имя
        words = line.strip().split()
        if len(words) >= 2:
            return [' '.join(words[:3])]

        return []

    def _extract_names_from_list(self, text: str) -> List[str]:
        """Извлечь имена из списка через точку с запятой или запятую"""
        names = []

        # Определяем разделитель: сначала проверяем точку с запятой, затем запятую
        if ';' in text:
            # Разделяем по точке с запятой
            parts = re.split(r';\s*', text)
        else:
            # Разделяем по запятым, учитывая что они находятся вне угловых скобок
            # Простой подход: разделяем по запятым и пробелам после них
            # Это работает, так как email-адреса в угловых скобках, а запятая разделителя всегда после закрывающей скобки
            parts = re.split(r',\s*', text)

        for part in parts:
            part = part.strip()
            if part:
                # _extract_name_from_email_line теперь возвращает список имен
                extracted_names = self._extract_name_from_email_line(part)
                if extracted_names:
                    names.extend(extracted_names)

        return names

    def _parse_date_time_string(self, date_time_str: str) -> Optional[Dict]:
        """Парсинг строки с датой и временем"""
        try:
            # Пример: "22 октября 2025 г. 15:00-16:00"
            # Ищем диапазон времени
            time_range_match = re.search(self.patterns['time_range'], date_time_str)
            if time_range_match:
                start_hour, start_min, end_hour, end_min = map(int, time_range_match.groups())
                duration_minutes = (end_hour * 60 + end_min) - (start_hour * 60 + start_min)
            else:
                # Ищем одиночное время
                single_time_match = re.search(self.patterns['single_time'], date_time_str)
                if single_time_match:
                    start_hour, start_min = map(int, single_time_match.groups())
                    # Предполагаем длительность 1 час
                    end_hour = start_hour + 1
                    end_min = start_min
                    duration_minutes = 60
                else:
                    return None

            # Ищем дату
            date_match = re.search(self.patterns['full_date_time'], date_time_str)
            if date_match:
                day, month_name, year, hour, minute = date_match.groups()
                month = self.months.get(month_name.lower())
                if month:
                    year = year or str(datetime.now().year)
                    start_time = datetime(int(year), month, int(day), start_hour, start_min)
                    end_time = datetime(int(year), month, int(day), end_hour, end_min)

                    return {
                        'start_time': start_time,
                        'end_time': end_time,
                        'duration_minutes': duration_minutes
                    }

            # Если не нашли полную дату, используем текущую дату
            today = datetime.now()
            start_time = today.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
            end_time = today.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)

            return {
                'start_time': start_time,
                'end_time': end_time,
                'duration_minutes': duration_minutes
            }

        except Exception as e:
            logger.error(f"Ошибка парсинга даты/времени: {e}")
            return None

    def _parse_date_string(self, date_str: str) -> Optional[datetime]:
        """Парсинг строки с датой"""
        try:
            # Пример: "22 октября 2025 г."
            date_match = re.search(self.patterns['full_date_time'], date_str)
            if date_match:
                day, month_name, year, hour, minute = date_match.groups()
                month = self.months.get(month_name.lower())
                if month:
                    year = year or str(datetime.now().year)
                    return datetime(int(year), month, int(day), int(hour or 0), int(minute or 0))

        except Exception as e:
            logger.error(f"Ошибка парсинга даты: {e}")
            return None

        return None

    def format_meeting_info_for_display(self, meeting_info: MeetingInfo) -> str:
        """Форматирование информации о встрече для отображения"""
        lines = []

        # Тема
        escaped_topic = self._escape_markdown(meeting_info.topic)
        lines.append(f"📋 **Тема:** {escaped_topic}")

        # Время
        if meeting_info.start_time:
            time_str = meeting_info.start_time.strftime("%d.%m.%Y %H:%M")
            if meeting_info.end_time:
                end_time_str = meeting_info.end_time.strftime("%H:%M")
                time_str += f" - {end_time_str}"
            lines.append(f"🕐 **Время:** {time_str}")

        # Участники
        if meeting_info.participants:
            participants_count = len(meeting_info.participants)
            lines.append(f"👥 **Участники ({participants_count}):**")

            for i, participant in enumerate(meeting_info.participants, 1):
                marker = "👑" if participant.is_organizer else "•"
                escaped_name = self._escape_markdown(participant.name)
                escaped_role = self._escape_markdown(participant.role) if participant.role else ""
                role_text = f", {escaped_role}" if escaped_role else ""
                lines.append(f"  {marker} {escaped_name}{role_text}")

        return "\n".join(lines)

    def validate_meeting_info(self, meeting_info: MeetingInfo) -> Tuple[bool, str]:
        """Валидация извлеченной информации о встрече"""
        warnings = []
        
        # Проверяем тему - если не указана, добавляем предупреждение, но не блокируем
        if not meeting_info.topic or meeting_info.topic == "Не указана":
            warnings.append("⚠️ Тема встречи не указана, будет использовано значение по умолчанию")

        # Строгая проверка участников - это критично
        if not meeting_info.participants:
            return False, "Не удалось найти участников встречи"

        # Проверяем что есть хотя бы один обязательный участник
        required_participants = [p for p in meeting_info.participants if p.is_required]
        if not required_participants:
            return False, "Не найдено обязательных участников"

        # Если есть предупреждения, возвращаем их, но валидация успешна
        if warnings:
            return True, warnings[0]
        
        return True, "Информация о встрече корректна"


# Глобальный экземпляр сервиса
meeting_info_service = MeetingInfoService()

