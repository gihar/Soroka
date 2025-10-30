"""
Сервис для работы со списком участников встречи
"""

import re
import csv
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path
from loguru import logger

from src.models.meeting_info import MeetingInfo


class ParticipantsService:
    """Сервис для парсинга и валидации списка участников"""
    
    def __init__(self, max_participants: int = 20):
        self.max_participants = max_participants
    
    def parse_participants_text(self, text: str) -> List[Dict[str, str]]:
        """
        Парсинг списка участников из текста
        
        Поддерживаемые форматы:
        - "Иван Петров, менеджер"
        - "Иван Петров"
        - "Иван Петров - менеджер"
        - "Иван Петров (менеджер)"
        
        Args:
            text: Текст со списком участников
            
        Returns:
            Список словарей с информацией об участниках
        """
        participants = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            participant = self._parse_single_line(line)
            if participant:
                participants.append(participant)
        
        logger.info(f"Распарсено {len(participants)} участников из текста")
        return participants
    
    def _parse_single_line(self, line: str) -> Optional[Dict[str, str]]:
        """Парсинг одной строки с участником"""
        # Убираем номера списков в начале (1., 2., -, •, etc)
        line = re.sub(r'^[\d\-•*]+[\.\)]\s*', '', line).strip()
        
        if not line:
            return None
        
        # Фильтруем строки с email-полями - они не являются участниками
        email_field_prefixes = ['от:', 'кому:', 'копия:', 'cc:', 'тема:', 'subject:', 
                                'когда:', 'when:', 'дата:', 'date:', 'время:', 'time:']
        if any(line.lower().startswith(prefix) for prefix in email_field_prefixes):
            return None
        
        participant = {"name": "", "role": ""}
        
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
        
        parsed = False
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                name = match.group(1).strip()
                role = match.group(2).strip()
                
                # Валидация: имя должно содержать хотя бы 2 символа
                if len(name) >= 2:
                    participant["name"] = name
                    participant["role"] = role
                    parsed = True
                    break
        
        # Если не удалось распарсить с ролью, берем всю строку как имя
        if not parsed:
            if len(line) >= 2:
                participant["name"] = line
                participant["role"] = ""
        
        # Возвращаем только если есть имя
        if participant["name"]:
            return participant
        
        return None
    
    def parse_participants_file(self, file_path: str) -> List[Dict[str, str]]:
        """
        Парсинг списка участников из файла
        
        Поддерживаемые форматы:
        - .txt файлы (один участник на строку)
        - .csv файлы (колонки: name, role)
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            Список словарей с информацией об участниках
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {file_path}")
        
        # Определяем формат файла
        extension = path.suffix.lower()
        
        if extension == '.csv':
            return self._parse_csv_file(file_path)
        elif extension in ['.txt', '.text']:
            # Читаем как текст
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return self.parse_participants_text(content)
        else:
            # Пробуем прочитать как текст для других форматов
            logger.warning(f"Неизвестный формат файла: {extension}. Пытаемся прочитать как текст")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return self.parse_participants_text(content)
    
    def _parse_csv_file(self, file_path: str) -> List[Dict[str, str]]:
        """Парсинг CSV файла"""
        participants = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            # Пробуем определить разделитель
            sample = f.read(1024)
            f.seek(0)
            
            # Определяем разделитель (запятая или точка с запятой)
            delimiter = ',' if sample.count(',') > sample.count(';') else ';'
            
            reader = csv.DictReader(f, delimiter=delimiter)
            
            for row in reader:
                # Ищем колонки с именем и ролью (поддержка разных вариантов названий)
                name_keys = ['name', 'Name', 'имя', 'Имя', 'ФИО', 'фио']
                role_keys = ['role', 'Role', 'роль', 'Роль', 'должность', 'Должность']
                
                name = ""
                role = ""
                
                # Находим имя
                for key in name_keys:
                    if key in row and row[key]:
                        name = row[key].strip()
                        break
                
                # Находим роль
                for key in role_keys:
                    if key in row and row[key]:
                        role = row[key].strip()
                        break
                
                # Если не нашли по ключам, берем первые две колонки
                if not name and len(row) > 0:
                    first_value = list(row.values())[0]
                    if first_value:
                        name = first_value.strip()
                
                if not role and len(row) > 1:
                    second_value = list(row.values())[1]
                    if second_value:
                        role = second_value.strip()
                
                if name:
                    participants.append({
                        "name": name,
                        "role": role or ""
                    })
        
        logger.info(f"Распарсено {len(participants)} участников из CSV файла")
        return participants

    def extract_from_meeting_text(self, text: str) -> Optional[MeetingInfo]:
        """
        Извлечь информацию о встрече из текста

        Args:
            text: Текст с информацией о встрече

        Returns:
            MeetingInfo или None если не удалось извлечь
        """
        try:
            from src.services.meeting_info_service import meeting_info_service

            meeting_info = meeting_info_service.extract_meeting_info(text)

            if meeting_info:
                logger.info(f"Извлечена информация о встрече: {meeting_info.topic}")
                return meeting_info
            else:
                logger.warning("Не удалось извлечь информацию о встрече")
                return None

        except Exception as e:
            logger.error(f"Ошибка при извлечении информации о встрече: {e}")
            return None

    def format_meeting_info_for_display(self, meeting_info: MeetingInfo) -> str:
        """
        Форматирование информации о встрече для отображения

        Args:
            meeting_info: Информация о встрече

        Returns:
            Отформатированная строка
        """
        from src.services.meeting_info_service import meeting_info_service
        return meeting_info_service.format_meeting_info_for_display(meeting_info)

    def validate_meeting_info(self, meeting_info: MeetingInfo) -> tuple[bool, str]:
        """
        Валидация информации о встрече

        Args:
            meeting_info: Информация о встрече

        Returns:
            Кортеж (валидна, сообщение)
        """
        from src.services.meeting_info_service import meeting_info_service
        return meeting_info_service.validate_meeting_info(meeting_info)
    
    def validate_participants(self, participants: List[Dict[str, str]]) -> tuple[bool, Optional[str]]:
        """
        Валидация списка участников
        
        Args:
            participants: Список участников
            
        Returns:
            Кортеж (валиден, сообщение об ошибке)
        """
        if not participants:
            return False, "Список участников пуст"
        
        if len(participants) > self.max_participants:
            return False, f"Слишком много участников (максимум {self.max_participants})"
        
        # Проверка на дубликаты имен
        names = [p["name"] for p in participants]
        if len(names) != len(set(names)):
            return False, "В списке есть дублирующиеся имена"
        
        # Проверка что все участники имеют имя
        for i, participant in enumerate(participants):
            if not participant.get("name"):
                return False, f"Участник #{i+1} не имеет имени"
            
            # Проверка минимальной длины имени
            if len(participant["name"]) < 2:
                return False, f"Имя '{participant['name']}' слишком короткое"
        
        return True, None
    
    def format_participants_for_display(self, participants: List[Dict[str, str]]) -> str:
        """
        Форматирование списка участников для отображения пользователю
        
        Args:
            participants: Список участников
            
        Returns:
            Форматированная строка
        """
        lines = ["📋 **Список участников:**\n"]
        
        for i, participant in enumerate(participants, 1):
            name = participant["name"]
            role = participant.get("role", "")
            
            if role:
                lines.append(f"{i}. {name} — {role}")
            else:
                lines.append(f"{i}. {name}")
        
        return "\n".join(lines)
    
    def _is_patronymic(self, word: str) -> bool:
        """
        Проверяет, является ли слово отчеством по характерным окончаниям
        
        Args:
            word: Слово для проверки
            
        Returns:
            True если слово похоже на отчество
        """
        patronymic_endings = ('вич', 'ович', 'евич', 'ич', 'вна', 'овна', 'евна', 'ична')
        return any(word.lower().endswith(ending) for ending in patronymic_endings)
    
    def _is_likely_surname(self, word: str) -> bool:
        """
        Проверяет, похоже ли слово на фамилию по типичным окончаниям
        
        Args:
            word: Слово для проверки
            
        Returns:
            True если слово похоже на фамилию
        """
        surname_endings = ('ов', 'ова', 'ев', 'ева', 'ин', 'ина', 'ский', 'ская', 
                          'ко', 'енко', 'ук', 'юк', 'ец', 'иц', 'ич')
        return any(word.lower().endswith(ending) for ending in surname_endings)
    
    def convert_full_name_to_short(self, full_name: str) -> str:
        """
        Преобразует полное ФИО в формат "Имя Фамилия" без отчества
        
        Поддерживает оба формата:
        - "Имя Отчество Фамилия" (например "Степан Евгеньевич Носов")
        - "Фамилия Имя Отчество" (например "Носов Степан Евгеньевич")
        
        Args:
            full_name: Полное имя (например "Тимченко Алексей Александрович" или "Алексей Тимченко")
            
        Returns:
            Имя в формате "Имя Фамилия" (например "Алексей Тимченко")
        """
        parts = full_name.strip().split()
        
        if len(parts) == 3:
            # Ищем отчество среди трех слов
            patronymic_idx = None
            for i, part in enumerate(parts):
                if self._is_patronymic(part):
                    patronymic_idx = i
                    break
            
            if patronymic_idx is not None:
                # Удаляем отчество, остаются имя и фамилия
                remaining = [p for i, p in enumerate(parts) if i != patronymic_idx]
                
                # Определяем порядок по позиции отчества
                if len(remaining) == 2:
                    # Если отчество в середине (позиция 1), формат точно "Имя Отчество Фамилия"
                    if patronymic_idx == 1:
                        return f"{remaining[0]} {remaining[1]}"
                    # Если отчество в начале (позиция 0), формат "Отчество Имя Фамилия" или "Отчество Фамилия Имя"
                    # Такое встречается редко, но на всякий случай проверим
                    elif patronymic_idx == 0:
                        # Проверяем фамильные окончания для определения порядка
                        if self._is_likely_surname(remaining[1]):
                            # Вероятно формат "Отчество Фамилия Имя"
                            return f"{remaining[1]} {remaining[0]}"
                        else:
                            # Вероятно формат "Отчество Имя Фамилия"
                            return f"{remaining[0]} {remaining[1]}"
                    # Если отчество в конце (позиция 2), формат "Имя Фамилия Отчество" или "Фамилия Имя Отчество"
                    else:  # patronymic_idx == 2
                        # Проверяем фамильные окончания для определения порядка
                        if self._is_likely_surname(remaining[0]):
                            # Фамилия Имя → Имя Фамилия
                            return f"{remaining[1]} {remaining[0]}"
                        else:
                            # Уже Имя Фамилия
                            return f"{remaining[0]} {remaining[1]}"
            
            # Если отчество не найдено, применяем старую логику
            # Предполагаем формат: Фамилия Имя Отчество → Имя Фамилия
            return f"{parts[1]} {parts[0]}"
        elif len(parts) == 2:
            # Формат: либо "Имя Фамилия", либо "Фамилия Имя"
            # Определяем по типичным паттернам окончаний фамилий
            first_word = parts[0]
            
            if self._is_likely_surname(first_word):
                # Фамилия Имя → Имя Фамилия
                return f"{parts[1]} {parts[0]}"
            else:
                # Уже в формате Имя Фамилия
                return full_name
        else:
            # Одно слово или больше 3 - возвращаем как есть
            return full_name
    
    def normalize_name_for_matching(self, name: str) -> str:
        """
        Приводит имя к каноническому виду для сопоставления
        
        Args:
            name: Строка с именем
        
        Returns:
            Нормализованная строка в нижнем регистре
        """
        if not name:
            return ""
        
        # Приводим ё к е для устойчивых сопоставлений
        normalized = (
            name.replace("ё", "е")
            .replace("Ё", "Е")
        )
        # Удаляем пунктуацию, оставляем буквы, цифры, пробелы и дефисы
        normalized = re.sub(r"[^\w\s\-]", " ", normalized, flags=re.UNICODE)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip().lower()
    
    def generate_name_variants(self, full_name: str) -> Set[str]:
        """
        Формирует набор допустимых вариантов имени для сопоставления
        
        Args:
            full_name: Полное имя участника
        
        Returns:
            Множество нормализованных вариантов имени
        """
        variants: Set[str] = set()
        
        normalized_full = self.normalize_name_for_matching(full_name)
        if not normalized_full:
            return variants
        
        variants.add(normalized_full)
        
        short_name = self.convert_full_name_to_short(full_name)
        normalized_short = self.normalize_name_for_matching(short_name)
        if normalized_short:
            variants.add(normalized_short)
        
        # Собираем токены из короткого и полного вариантов
        token_sources = []
        if normalized_short:
            token_sources.append(normalized_short.split())
        if normalized_full and normalized_full != normalized_short:
            token_sources.append(normalized_full.split())
        
        for tokens in token_sources:
            if not tokens:
                continue
            
            # Основной вариант: первые два слова
            if len(tokens) >= 2:
                first, second = tokens[0], tokens[1]
                variants.add(f"{first} {second}".strip())
                variants.add(f"{second} {first}".strip())
                variants.add(first)
                variants.add(second)
            else:
                variants.add(tokens[0])
        
        # Удаляем пустые варианты
        variants = {variant for variant in variants if variant}
        return variants
    
    def build_name_lookup(self, participants: List[Dict[str, str]]) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
        """
        Создает карту для сопоставления нормализованных имен с участниками
        
        Args:
            participants: Список участников
        
        Returns:
            Кортеж из словаря вариантов и множества неоднозначных вариантов
        """
        lookup: Dict[str, Dict[str, Any]] = {}
        ambiguous_variants: Set[str] = set()
        
        for index, participant in enumerate(participants):
            full_name = participant.get("name", "") or ""
            if not full_name.strip():
                continue
            
            display_name = self.convert_full_name_to_short(full_name).strip() or full_name.strip()
            display_name = re.sub(r"\s+", " ", display_name)
            
            variants = self.generate_name_variants(full_name)
            for variant in variants:
                if not variant:
                    continue
                
                if variant in lookup and lookup[variant]["index"] != index:
                    ambiguous_variants.add(variant)
                    lookup.pop(variant, None)
                    continue
                
                lookup[variant] = {
                    "index": index,
                    "display_name": display_name,
                    "original_name": full_name.strip(),
                }
        
        return lookup, ambiguous_variants
    
    def format_participants_for_llm(self, participants: List[Dict[str, str]]) -> str:
        """
        Форматирование списка участников для передачи в LLM в формате "Имя Фамилия"
        
        Args:
            participants: Список участников
            
        Returns:
            Форматированная строка для промпта
        """
        lines = []
        
        for participant in participants:
            full_name = participant["name"]
            # Преобразуем в формат "Имя Фамилия"
            short_name = self.convert_full_name_to_short(full_name)
            role = participant.get("role", "")
            
            if role:
                lines.append(f"- {short_name} ({role})")
            else:
                lines.append(f"- {short_name}")
        
        return "\n".join(lines)
    
    def participants_to_json(self, participants: List[Dict[str, str]]) -> str:
        """Сериализация участников в JSON для сохранения"""
        import json
        return json.dumps(participants, ensure_ascii=False)
    
    def participants_from_json(self, json_str: str) -> List[Dict[str, str]]:
        """Десериализация участников из JSON"""
        import json
        try:
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"Ошибка при десериализации участников: {e}")
            return []


# Глобальный экземпляр сервиса
participants_service = ParticipantsService()
