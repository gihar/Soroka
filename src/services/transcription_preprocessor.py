"""
Сервис для предобработки текста транскрипции
Удаляет шум, междометия, нормализует текст для улучшения качества протоколов
"""

import re
from typing import List, Tuple

from loguru import logger


class TranscriptionPreprocessor:
    """Препроцессор для очистки и нормализации текста транскрипции"""
    
    # Русские междометия — только звуки без смысла. Слова-«паразиты» вроде
    # «значит», «допустим», «в принципе», «типа» несут смысл («это значит, что
    # срок сдвигается»; «допустим, 500 тысяч» — оговорка о допущении) и
    # остаются: модель видит этот текст при перегенерации и без диаризации.
    RUSSIAN_FILLERS = [
        r'\bэ+[-\s]*э+\b',  # э-э, ээ
        r'\bм+[-\s]*м+\b',  # м-м, мм
        r'\bа+[-\s]*а+\b',  # а-а, аа
    ]
    
    # Английские междометия
    ENGLISH_FILLERS = [
        r'\buh+\b',
        r'\bum+\b',
        r'\bah+\b',
        r'\blike\b',
        r'\byou\s+know\b',
        r'\bi\s+mean\b',
        r'\bactually\b',
        r'\bbasically\b',
        r'\bkind\s+of\b',
        r'\bsort\s+of\b',
    ]
    
    # Повторы слов (одно слово 3+ раза подряд)
    WORD_REPETITION = r'\b(\w+)(\s+\1){2,}\b'
    
    def __init__(self, language: str = "ru"):
        """
        Инициализация препроцессора
        
        Args:
            language: Язык транскрипции (ru или en)
        """
        self.language = language
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Компилировать regex паттерны для эффективности"""
        fillers = self.RUSSIAN_FILLERS if self.language == "ru" else self.ENGLISH_FILLERS
        
        # Объединяем все паттерны заполнителей
        self.filler_pattern = re.compile(
            '|'.join(fillers),
            re.IGNORECASE | re.UNICODE
        )
        
        self.repetition_pattern = re.compile(
            self.WORD_REPETITION,
            re.IGNORECASE | re.UNICODE
        )
    
    def remove_fillers(self, text: str) -> Tuple[str, int]:
        """
        Удалить междометия и заполнители
        
        Args:
            text: Исходный текст
            
        Returns:
            Tuple[очищенный текст, количество удаленных заполнителей]
        """
        original_length = len(text)
        cleaned = self.filler_pattern.sub('', text)
        
        # Подсчет удаленных заполнителей
        removed_count = (original_length - len(cleaned)) // 3  # Примерная оценка
        
        return cleaned, removed_count
    
    def remove_repetitions(self, text: str) -> str:
        """
        Удалить повторы слов (например: "да да да" -> "да")
        
        Args:
            text: Исходный текст
            
        Returns:
            Текст без повторов
        """
        def replace_repetition(match):
            # Оставляем только первое вхождение слова
            return match.group(1)
        
        return self.repetition_pattern.sub(replace_repetition, text)
    
    def normalize_punctuation(self, text: str) -> str:
        """
        Нормализовать пунктуацию
        
        Args:
            text: Исходный текст
            
        Returns:
            Текст с нормализованной пунктуацией
        """
        # Схлопываем пробелы внутри строки; переводы строк — границы реплик,
        # их сохраняем
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r' *\n *', '\n', text)
        
        # Нормализуем точки (удаляем множественные)
        text = re.sub(r'\.{2,}', '.', text)
        
        # Нормализуем запятые
        text = re.sub(r',{2,}', ',', text)
        
        # Удаляем пробелы перед пунктуацией
        text = re.sub(r' +([.,!?;:])', r'\1', text)
        
        # Пробел после запятой и знаков конца фразы, если дальше буква. После
        # точки и двоеточия — только перед заглавной: иначе рвутся file.py,
        # http://, v2.1
        text = re.sub(r'([,!?;])([^\W\d_])', r'\1 \2', text)
        text = re.sub(r'([.:])([A-ZА-ЯЁ])', r'\1 \2', text)
        
        return text.strip()
    
    def split_into_sentences(self, text: str) -> List[str]:
        """
        Разделить текст на предложения
        
        Args:
            text: Исходный текст
            
        Returns:
            Список предложений
        """
        # Базовое разделение по точкам, вопросительным и восклицательным знакам
        sentences = re.split(r'[.!?]+\s+', text)
        
        # Фильтруем пустые строки
        sentences = [s.strip() for s in sentences if s.strip()]
        
        return sentences
    
    def preprocess(self, text: str) -> dict:
        """
        Выполнить полную предобработку текста
        
        Args:
            text: Исходный текст транскрипции
            
        Returns:
            Dict с результатами предобработки:
            - cleaned_text: Очищенный текст
            - statistics: Статистика предобработки
        """
        logger.info("Начало предобработки транскрипции")
        
        stats = {
            'original_length': len(text),
            'fillers_removed': 0,
            'repetitions_removed': 0,
            'sentences_count': 0
        }
        
        # Шаг 1: Удаление заполнителей
        cleaned_text, fillers_count = self.remove_fillers(text)
        stats['fillers_removed'] = fillers_count
        
        # Шаг 2: Удаление повторов
        before_rep = len(cleaned_text)
        cleaned_text = self.remove_repetitions(cleaned_text)
        stats['repetitions_removed'] = (before_rep - len(cleaned_text)) // 5  # Примерная оценка
        
        # Шаг 3: Нормализация пунктуации
        cleaned_text = self.normalize_punctuation(cleaned_text)
        
        # Шаг 4: Разделение на предложения
        sentences = self.split_into_sentences(cleaned_text)
        stats['sentences_count'] = len(sentences)
        
        stats['cleaned_length'] = len(cleaned_text)
        if stats['original_length'] == 0:
            logger.warning("Получена пустая транскрипция, метрики сокращения не рассчитываются")
            stats['reduction_percent'] = 0.0
        else:
            stats['reduction_percent'] = round(
                (stats['original_length'] - stats['cleaned_length']) / stats['original_length'] * 100, 2
            )
        
        logger.info(
            f"Предобработка завершена: удалено {stats['fillers_removed']} заполнителей, "
            f"{stats['repetitions_removed']} повторов, сокращение на {stats['reduction_percent']}%"
        )
        
        return {
            'cleaned_text': cleaned_text,
            'statistics': stats,
            'sentences': sentences
        }


# Глобальный экземпляр препроцессора
_preprocessor_cache = {}

def get_preprocessor(language: str = "ru") -> TranscriptionPreprocessor:
    """
    Получить экземпляр препроцессора для языка
    
    Args:
        language: Код языка
        
    Returns:
        Экземпляр TranscriptionPreprocessor
    """
    if language not in _preprocessor_cache:
        _preprocessor_cache[language] = TranscriptionPreprocessor(language)
    return _preprocessor_cache[language]
