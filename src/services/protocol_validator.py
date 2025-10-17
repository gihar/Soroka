"""
Сервис для валидации и оценки качества сгенерированных протоколов
"""

import re
from typing import Dict, Any, List, Optional
from loguru import logger

from src.models.diarization_analysis import ValidationResult


class ProtocolValidator:
    """Валидатор для проверки качества протоколов"""
    
    def __init__(self):
        """Инициализация валидатора"""
        self.min_field_length = 10  # Минимальная длина значимого поля
        self.not_specified_values = [
            "не указано",
            "not specified",
            "н/д",
            "n/a",
            "unknown",
            "неизвестно"
        ]
    
    def validate_completeness(
        self,
        protocol: Dict[str, Any],
        template_variables: Dict[str, str]
    ) -> tuple[float, List[str], List[str]]:
        """
        Проверить полноту протокола
        
        Args:
            protocol: Сгенерированный протокол
            template_variables: Ожидаемые переменные шаблона
            
        Returns:
            (оценка полноты, список отсутствующих полей, список пустых полей)
        """
        missing_fields = []
        empty_fields = []
        
        # Проверяем наличие всех ожидаемых полей
        for field_name in template_variables.keys():
            if field_name not in protocol:
                missing_fields.append(field_name)
                continue
            
            value = protocol[field_name]
            
            # Проверяем, не пустое ли поле
            if not value or (isinstance(value, str) and len(value.strip()) < self.min_field_length):
                empty_fields.append(field_name)
                continue
            
            # Проверяем, не содержит ли "Не указано"
            if isinstance(value, str):
                value_lower = value.lower().strip()
                if any(not_spec in value_lower for not_spec in self.not_specified_values):
                    empty_fields.append(field_name)
        
        # Вычисляем оценку полноты
        total_fields = len(template_variables)
        filled_fields = total_fields - len(missing_fields) - len(empty_fields)
        completeness_score = filled_fields / total_fields if total_fields > 0 else 0
        
        return completeness_score, missing_fields, empty_fields
    
    def validate_structure(self, protocol: Dict[str, Any]) -> tuple[float, List[str]]:
        """
        Проверить структурную корректность протокола
        
        Args:
            protocol: Сгенерированный протокол
            
        Returns:
            (оценка структуры, список предупреждений)
        """
        warnings = []
        score_components = []
        
        # Проверка 1: Все значения должны быть строками (не вложенные объекты)
        for key, value in protocol.items():
            if isinstance(value, (dict, list)):
                warnings.append(f"Поле '{key}' содержит вложенную структуру вместо строки")
                score_components.append(0)
            else:
                score_components.append(1)
        
        # Проверка 2: Проверяем форматирование списков
        for key, value in protocol.items():
            if isinstance(value, str) and '\n' in value:
                # Проверяем, что списки форматированы правильно (с дефисами)
                lines = value.split('\n')
                list_items = [l for l in lines if l.strip().startswith('-')]
                
                # Если есть элементы списка, проверяем их форматирование
                if list_items:
                    for item in list_items:
                        # Проверяем, что нет точек в конце
                        if item.rstrip().endswith('.') and not item.rstrip().endswith('...'):
                            warnings.append(f"Поле '{key}': элемент списка заканчивается точкой")
                            score_components.append(0.8)
                            break
                        
                        # Проверяем, что нет нумерации
                        if re.match(r'^\s*-?\s*\d+[.)]\s', item):
                            warnings.append(f"Поле '{key}': использована нумерация вместо дефисов")
                            score_components.append(0.7)
                            break
                    else:
                        score_components.append(1)
        
        # Проверка 3: Проверяем наличие JSON-структур в текстовых полях
        for key, value in protocol.items():
            if isinstance(value, str):
                # Простая проверка на наличие JSON-подобных структур
                if re.search(r'\{[^}]+\}', value):
                    warnings.append(f"Поле '{key}' содержит JSON-структуры в тексте")
                    score_components.append(0.5)
        
        # Вычисляем итоговую оценку структуры
        structure_score = sum(score_components) / len(score_components) if score_components else 1.0
        
        return structure_score, warnings
    
    def check_factual_accuracy(
        self,
        protocol: Dict[str, Any],
        transcription: str
    ) -> tuple[float, List[str]]:
        """
        Проверить фактологическую точность (нет выдуманных данных)
        
        Args:
            protocol: Сгенерированный протокол
            transcription: Исходная транскрипция
            
        Returns:
            (оценка точности, список предупреждений)
        """
        warnings = []
        accuracy_scores = []
        
        # Проверяем каждое поле на наличие в транскрипции
        for key, value in protocol.items():
            if not isinstance(value, str) or len(value) < 10:
                continue
            
            # Извлекаем ключевые слова из значения (исключая служебные слова)
            words = self._extract_keywords(value)
            
            if not words:
                continue
            
            # Проверяем, сколько ключевых слов присутствует в транскрипции
            found_words = 0
            for word in words[:10]:  # Проверяем максимум 10 ключевых слов
                if word.lower() in transcription.lower():
                    found_words += 1
            
            # Если менее 30% ключевых слов найдено - возможна выдумка
            match_ratio = found_words / min(len(words), 10)
            
            if match_ratio < 0.3:
                warnings.append(
                    f"Поле '{key}': низкое соответствие с транскрипцией ({match_ratio:.0%})"
                )
                accuracy_scores.append(match_ratio)
            else:
                accuracy_scores.append(1.0)
        
        # Вычисляем итоговую оценку точности
        factual_accuracy = sum(accuracy_scores) / len(accuracy_scores) if accuracy_scores else 0.9
        
        return factual_accuracy, warnings
    
    def check_diarization_usage(
        self,
        protocol: Dict[str, Any],
        diarization_data: Optional[Dict[str, Any]]
    ) -> tuple[float, List[str]]:
        """
        Проверить, насколько хорошо использованы данные диаризации
        
        Args:
            protocol: Сгенерированный протокол
            diarization_data: Данные диаризации
            
        Returns:
            (оценка использования диаризации, список рекомендаций)
        """
        if not diarization_data or not diarization_data.get('speakers_text'):
            # Нет данных диаризации - оценка не применима
            return 1.0, []
        
        suggestions = []
        usage_scores = []
        
        # Проверяем упоминание спикеров в протоколе
        speakers = list(diarization_data.get('speakers_text', {}).keys())
        protocol_text = ' '.join(str(v) for v in protocol.values())
        
        # Подсчитываем, сколько спикеров упомянуто
        mentioned_speakers = 0
        for speaker in speakers:
            if speaker.lower() in protocol_text.lower():
                mentioned_speakers += 1
        
        speaker_mention_ratio = mentioned_speakers / len(speakers) if speakers else 1.0
        usage_scores.append(speaker_mention_ratio)
        
        if speaker_mention_ratio < 0.5:
            suggestions.append(
                f"Использованы данные только о {mentioned_speakers} из {len(speakers)} спикеров"
            )
        
        # Проверяем, есть ли информация об ответственных в задачах
        action_fields = [
            'action_items', 'tasks', 'поручения', 'задачи'
        ]
        
        has_responsible_info = False
        for field in action_fields:
            if field in protocol and isinstance(protocol[field], str):
                value = protocol[field]
                # Ищем паттерны указания ответственных
                if re.search(r'ответственный|responsible|assignee|спикер \d+|speaker \d+', value, re.IGNORECASE):
                    has_responsible_info = True
                    break
        
        if not has_responsible_info and speakers:
            suggestions.append(
                "Не указаны ответственные за задачи из числа спикеров"
            )
            usage_scores.append(0.5)
        else:
            usage_scores.append(1.0)
        
        # Вычисляем итоговую оценку использования диаризации
        diarization_usage = sum(usage_scores) / len(usage_scores) if usage_scores else 0.8
        
        return diarization_usage, suggestions
    
    def calculate_quality_score(
        self,
        protocol: Dict[str, Any],
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Вычислить общую оценку качества протокола
        
        Args:
            protocol: Сгенерированный протокол
            transcription: Исходная транскрипция
            template_variables: Ожидаемые переменные шаблона
            diarization_data: Данные диаризации (опционально)
            
        Returns:
            Результат валидации с оценками и рекомендациями
        """
        logger.info("Начало валидации протокола")
        
        # 1. Проверка полноты
        completeness, missing, empty = self.validate_completeness(protocol, template_variables)
        
        # 2. Проверка структуры
        structure, struct_warnings = self.validate_structure(protocol)
        
        # 3. Проверка фактологической точности
        factual_accuracy, fact_warnings = self.check_factual_accuracy(protocol, transcription)
        
        # 4. Проверка использования диаризации
        diarization_usage, diar_suggestions = self.check_diarization_usage(protocol, diarization_data)
        
        # Объединяем все предупреждения и рекомендации
        all_warnings = struct_warnings + fact_warnings
        all_suggestions = diar_suggestions
        
        # Вычисляем общую оценку (взвешенное среднее)
        weights = {
            'completeness': 0.35,
            'structure': 0.25,
            'factual_accuracy': 0.30,
            'diarization_usage': 0.10
        }
        
        overall_score = (
            completeness * weights['completeness'] +
            structure * weights['structure'] +
            factual_accuracy * weights['factual_accuracy'] +
            diarization_usage * weights['diarization_usage']
        )
        
        # Определяем, валиден ли протокол (минимальный порог 0.6)
        is_valid = overall_score >= 0.6
        
        result = ValidationResult(
            is_valid=is_valid,
            completeness_score=round(completeness, 2),
            structure_score=round(structure, 2),
            factual_accuracy_score=round(factual_accuracy, 2),
            diarization_usage_score=round(diarization_usage, 2),
            overall_score=round(overall_score, 2),
            missing_fields=missing,
            empty_fields=empty,
            warnings=all_warnings,
            suggestions=all_suggestions
        )
        
        logger.info(
            f"Валидация завершена: общая оценка {result.overall_score}, "
            f"валиден: {result.is_valid}"
        )
        
        return result
    
    def suggest_improvements(
        self,
        validation_result: ValidationResult
    ) -> List[str]:
        """
        Сформировать рекомендации по улучшению протокола
        
        Args:
            validation_result: Результат валидации
            
        Returns:
            Список рекомендаций
        """
        recommendations = []
        
        # Рекомендации по полноте
        if validation_result.completeness_score < 0.7:
            recommendations.append(
                "Необходимо заполнить больше полей протокола. "
                f"Отсутствуют или пусты: {', '.join(validation_result.empty_fields[:5])}"
            )
        
        # Рекомендации по структуре
        if validation_result.structure_score < 0.8:
            recommendations.append(
                "Улучшите структурирование протокола: используйте дефисы для списков, "
                "избегайте вложенных JSON-структур"
            )
        
        # Рекомендации по точности
        if validation_result.factual_accuracy_score < 0.7:
            recommendations.append(
                "Проверьте фактологическую точность: убедитесь, что вся информация "
                "присутствует в исходной транскрипции"
            )
        
        # Рекомендации по диаризации
        if validation_result.diarization_usage_score < 0.7:
            recommendations.append(
                "Используйте больше информации о спикерах: укажите ответственных за задачи, "
                "детализируйте вклад участников"
            )
        
        # Добавляем конкретные рекомендации из результата
        recommendations.extend(validation_result.suggestions)
        
        return recommendations
    
    def _extract_keywords(self, text: str) -> List[str]:
        """
        Извлечь ключевые слова из текста (исключая служебные слова)
        
        Args:
            text: Исходный текст
            
        Returns:
            Список ключевых слов
        """
        # Простой список стоп-слов (русские и английские)
        stop_words = {
            'и', 'в', 'на', 'с', 'по', 'для', 'к', 'о', 'от', 'из', 'за', 'у', 'до', 'при',
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
            'это', 'этот', 'быть', 'мочь', 'который', 'этих', 'был', 'такой', 'как', 'есть',
            'было', 'ответственный', 'указано', 'не'
        }
        
        # Разбиваем текст на слова
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Фильтруем стоп-слова и короткие слова
        keywords = [w for w in words if len(w) > 3 and w not in stop_words]
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_keywords = []
        for word in keywords:
            if word not in seen:
                seen.add(word)
                unique_keywords.append(word)
        
        return unique_keywords


# Глобальный экземпляр валидатора
protocol_validator = ProtocolValidator()

