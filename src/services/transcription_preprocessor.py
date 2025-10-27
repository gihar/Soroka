"""
Сервис для предобработки текста транскрипции
Удаляет шум, междометия, нормализует текст для улучшения качества протоколов
"""

import re
from typing import List, Tuple, Optional
from loguru import logger


class TranscriptionPreprocessor:
    """Препроцессор для очистки и нормализации текста транскрипции"""
    
    # Русские междометия и заполнители
    RUSSIAN_FILLERS = [
        r'\bэ+[-\s]*э+\b',  # э-э, ээ
        r'\bм+[-\s]*м+\b',  # м-м, мм
        r'\bа+[-\s]*а+\b',  # а-а, аа
        r'\bну\s+вот\b',
        r'\bну\s+это\b',
        r'\bну\s+как\s+бы\b',
        r'\bкак\s+бы\b',
        r'\bтак\s+сказать\b',
        r'\bвообще\s+говоря\b',
        r'\bв\s+общем[-,\s]+то\b',
        r'\bв\s+принципе\b',
        r'\bдопустим\b',
        r'\bпредположим\b',
        r'\bзначит\b',
        r'\bкороче\b',
        r'\bблин\b',
        r'\bтипа\b',
        r'\bчисто\b',
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
        # Удаляем множественные пробелы
        text = re.sub(r'\s+', ' ', text)
        
        # Нормализуем точки (удаляем множественные)
        text = re.sub(r'\.{2,}', '.', text)
        
        # Нормализуем запятые
        text = re.sub(r',{2,}', ',', text)
        
        # Удаляем пробелы перед пунктуацией
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        
        # Добавляем пробел после пунктуации, если его нет
        text = re.sub(r'([.,!?;:])([^\s\d])', r'\1 \2', text)
        
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
    
    def group_speaker_turns(self, formatted_transcript: str) -> str:
        """
        Группировать последовательные реплики одного спикера
        
        Args:
            formatted_transcript: Форматированная транскрипция с метками спикеров
            
        Returns:
            Сгруппированная транскрипция
        """
        lines = formatted_transcript.split('\n')
        grouped_lines = []
        current_speaker = None
        current_text = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Проверяем, начинается ли строка с метки спикера
            speaker_match = re.match(r'^(Спикер \d+|Speaker \d+):\s*(.*)$', line)
            
            if speaker_match:
                speaker = speaker_match.group(1)
                text = speaker_match.group(2)
                
                if speaker == current_speaker:
                    # Тот же спикер - добавляем к текущему тексту
                    current_text.append(text)
                else:
                    # Новый спикер - сохраняем предыдущего
                    if current_speaker and current_text:
                        grouped_lines.append(f"{current_speaker}: {' '.join(current_text)}")
                    
                    current_speaker = speaker
                    current_text = [text]
            else:
                # Строка без метки спикера - добавляем к текущему тексту
                if current_text:
                    current_text.append(line)
        
        # Добавляем последнюю группу
        if current_speaker and current_text:
            grouped_lines.append(f"{current_speaker}: {' '.join(current_text)}")
        
        return '\n'.join(grouped_lines)
    
    def fix_common_recognition_errors(self, text: str) -> str:
        """
        Исправить распространенные ошибки распознавания
        
        Args:
            text: Исходный текст
            
        Returns:
            Текст с исправленными ошибками
        """
        corrections = {
            # Русские распространенные ошибки
            r'\bв общим\b': 'в общем',
            r'\bв общем то\b': 'в общем-то',
            r'\bпотому что\b': 'потому что',
            r'\bпо этому\b': 'поэтому',
            r'\bтак же\b': 'также',
            r'\bчто бы\b': 'чтобы',
            r'\bи так\b': 'итак',
            # Английские распространенные ошибки
            r'\ba lot of\b': 'a lot of',
            r'\bgoing to\b': 'going to',
        }
        
        for pattern, replacement in corrections.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        return text
    
    def preprocess(self, text: str, formatted_transcript: Optional[str] = None) -> dict:
        """
        Выполнить полную предобработку текста
        
        Args:
            text: Исходный текст транскрипции
            formatted_transcript: Форматированная транскрипция с метками спикеров (опционально)
            
        Returns:
            Dict с результатами предобработки:
            - cleaned_text: Очищенный текст
            - cleaned_formatted: Очищенная форматированная транскрипция (если была передана)
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
        
        # Шаг 3: Исправление распространенных ошибок
        cleaned_text = self.fix_common_recognition_errors(cleaned_text)
        
        # Шаг 4: Нормализация пунктуации
        cleaned_text = self.normalize_punctuation(cleaned_text)
        
        # Шаг 5: Разделение на предложения
        sentences = self.split_into_sentences(cleaned_text)
        stats['sentences_count'] = len(sentences)
        
        # Шаг 6: Группировка реплик спикеров (если есть форматированная транскрипция)
        cleaned_formatted = None
        if formatted_transcript:
            # Применяем те же очистки к форматированной транскрипции
            temp_formatted, _ = self.remove_fillers(formatted_transcript)
            temp_formatted = self.remove_repetitions(temp_formatted)
            temp_formatted = self.fix_common_recognition_errors(temp_formatted)
            temp_formatted = self.normalize_punctuation(temp_formatted)
            cleaned_formatted = self.group_speaker_turns(temp_formatted)
        
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
            'cleaned_formatted': cleaned_formatted,
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
