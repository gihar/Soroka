"""
Модуль для интеграции с различными LLM провайдерами
"""

import json
import asyncio
import httpx
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List, TYPE_CHECKING
from loguru import logger
from config import settings

import openai
from anthropic import Anthropic

# Импорт для retry логики
from src.reliability.retry import RetryManager, LLM_RETRY_CONFIG

# Импорт исключений
from src.exceptions.processing import LLMInsufficientCreditsError

# Импорт правил для полей протокола и функции генерации динамических правил
from src.prompts.prompts import (
    FIELD_SPECIFIC_RULES, 
    _build_field_specific_rules,
    build_analysis_prompt,
    build_analysis_system_prompt,
    build_generation_prompt,
    build_generation_system_prompt
)

# Импорт JSON Schema для structured outputs
from src.models.llm_schemas import (
    PROTOCOL_SCHEMA,
    MEETING_ANALYSIS_SCHEMA,
    PROTOCOL_DATA_SCHEMA
)

# Импорт утилит для оптимизации контекста
from src.utils.context_extraction import (
    extract_relevant_excerpts,
    build_structure_summary,
    add_prompt_caching_markers,
    build_anthropic_messages_with_caching
)

# Импорт утилит для логирования кеширования токенов
from src.utils.token_cache_logger import log_cached_tokens_usage, check_cache_support

# -------------------------------------------------------------
# Утилита для безопасного парсинга JSON
# -------------------------------------------------------------
def safe_json_parse(content: str, context: str = "LLM response") -> Dict[str, Any]:
    """
    Безопасный парсинг JSON с обработкой различных edge cases.
    
    Args:
        content: Строка с JSON для парсинга
        context: Контекст для логирования (например, "OpenAI response")
        
    Returns:
        Распарсенный JSON словарь
        
    Raises:
        ValueError: Если не удалось распарсить JSON после всех попыток
    """
    if not content or not content.strip():
        raise ValueError(f"Получен пустой ответ в {context}")
    
    original_content = content
    content_length = len(content)
    
    # Шаг 1: Удаляем BOM (Byte Order Mark) и невидимые символы
    content = content.strip()
    if content.startswith('\ufeff'):
        content = content[1:]
        logger.debug(f"Удален BOM из {context}")
    
    # Шаг 2: Попытка прямого парсинга
    try:
        result = json.loads(content)
        logger.debug(f"Прямой парсинг JSON успешен для {context}")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"Прямой парсинг JSON не удался для {context}: {e}")
    
    # Шаг 3: Удаляем markdown блоки (```json ... ``` или ``` ... ```)
    import re
    markdown_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
    markdown_match = re.search(markdown_pattern, content, re.DOTALL)
    if markdown_match:
        content = markdown_match.group(1).strip()
        logger.debug(f"Извлечен JSON из markdown блока в {context}")
        try:
            result = json.loads(content)
            logger.info(f"Парсинг JSON после удаления markdown успешен для {context}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"Парсинг после удаления markdown не удался для {context}: {e}")
    
    # Шаг 4: Ищем JSON объект в тексте (между первой { и последней })
    start_idx = content.find('{')
    end_idx = content.rfind('}') + 1
    
    if start_idx != -1 and end_idx > start_idx:
        json_str = content[start_idx:end_idx]
        logger.debug(f"Извлечен JSON из позиции {start_idx} до {end_idx} в {context}")
        try:
            result = json.loads(json_str)
            logger.info(f"Парсинг извлеченного JSON успешен для {context}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"Парсинг извлеченного JSON не удался для {context}: {e}")
    
    # Шаг 5: Попытка найти JSON массив (между первой [ и последней ])
    start_idx = content.find('[')
    end_idx = content.rfind(']') + 1
    
    if start_idx != -1 and end_idx > start_idx:
        json_str = content[start_idx:end_idx]
        logger.debug(f"Извлечен JSON массив из позиции {start_idx} до {end_idx} в {context}")
        try:
            result = json.loads(json_str)
            logger.info(f"Парсинг JSON массива успешен для {context}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"Парсинг JSON массива не удался для {context}: {e}")
    
    # Шаг 6: Последняя попытка - удаляем все до первой { и после последней }
    # и пытаемся исправить common issues
    try:
        # Удаляем комментарии в стиле // и /* */
        content_no_comments = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        content_no_comments = re.sub(r'/\*.*?\*/', '', content_no_comments, flags=re.DOTALL)
        
        # Удаляем trailing commas
        content_no_comments = re.sub(r',(\s*[}\]])', r'\1', content_no_comments)
        
        result = json.loads(content_no_comments)
        logger.info(f"Парсинг JSON после очистки комментариев успешен для {context}")
        return result
    except json.JSONDecodeError:
        pass
    
    # Все попытки исчерпаны - логируем подробную информацию и выбрасываем ошибку
    logger.error(f"❌ Не удалось распарсить JSON в {context}")
    logger.error(f"Длина ответа: {content_length} символов")
    logger.error(f"Первые 500 символов: {original_content[:500]}")
    logger.error(f"Последние 500 символов: {original_content[-500:] if len(original_content) > 500 else ''}")
    
    # Пытаемся найти позицию ошибки
    try:
        json.loads(original_content)
    except json.JSONDecodeError as final_error:
        error_pos = getattr(final_error, 'pos', None)
        if error_pos and error_pos < len(original_content):
            # Показываем контекст вокруг ошибки
            start = max(0, error_pos - 50)
            end = min(len(original_content), error_pos + 50)
            context_str = original_content[start:end]
            logger.error(f"Контекст ошибки (позиция {error_pos}): ...{context_str}...")
        
        raise ValueError(
            f"Не удалось распарсить JSON в {context}: {final_error}. "
            f"Длина: {content_length} символов. "
            f"Проверьте логи для подробностей."
        )
    
    raise ValueError(f"Не удалось распарсить JSON в {context}. Длина: {content_length} символов.")

class LLMProvider(ABC):
    """Абстрактный базовый класс для LLM провайдеров"""
    
    @abstractmethod
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол на основе транскрипции и шаблона"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Проверить доступность провайдера"""
        pass


# -------------------------------------------------------------
# Унифицированные билдеры промптов для всех провайдеров
# -------------------------------------------------------------
def _build_system_prompt(
    transcription: Optional[str] = None,
    diarization_analysis: Optional[Dict[str, Any]] = None,
    llm_meeting_type: Optional[str] = None
) -> str:
    """
    Строгая системная политика для получения профессионального протокола.
    Автоматически выбирает специализированный промпт если включена классификация.

    Args:
        transcription: Текст транскрипции (для классификации)
        diarization_analysis: Анализ диаризации (для классификации)
        llm_meeting_type: Тип встречи определенный LLM (приоритет над классификатором)

    Returns:
        Системный промпт (базовый или специализированный)
    """
    # Приоритет: LLM-определение > классификатор > базовый промпт
    meeting_type = None

    # 1. Если LLM определила тип встречи - используем его
    if llm_meeting_type:
        meeting_type = llm_meeting_type
        logger.info(f"Использую тип встречи определенный LLM: {meeting_type}")
    # 2. Иначе если включена классификация и есть транскрипция
    elif settings.meeting_type_detection and transcription:
        try:
            from src.services.meeting_classifier import meeting_classifier
            # Классифицируем встречу
            meeting_type, _ = meeting_classifier.classify(
                transcription,
                diarization_analysis
            )
            logger.info(f"Использую тип встречи определенный классификатором: {meeting_type}")

        except Exception as e:
            logger.warning(f"Ошибка при классификации встречи: {e}. Используем базовый промпт")

    # Если определен тип встречи, логируем для информации (но используем базовый промпт)
    if meeting_type:
        logger.info(f"Определен тип встречи: {meeting_type} (используем базовый промпт)")
    
    # Базовый промпт (общий для всех режимов)
    base_prompt = (
        "Ты — профессиональный протоколист высшей квалификации с опытом документирования "
        "деловых встреч, совещаний и переговоров.\n\n"
        
        "ТВОЯ РОЛЬ:\n"
        "- Извлекать и структурировать ключевую информацию из стенограмм встреч\n"
        "- Создавать четкие, лаконичные и информативные протоколы\n"
        "- Сохранять объективность и фактологическую точность\n\n"
        
        "ФУНДАМЕНТАЛЬНЫЕ ПРИНЦИПЫ ТОЧНОСТИ:\n"
        "- АБСОЛЮТНАЯ ПОЛНОТА: Анализируй ВСЮ транскрипцию от первого до последнего слова. "
        "Каждая упомянутая тема, идея, вопрос или комментарий должны быть отражены в протоколе\n"
        "- ФАКТИЧЕСКАЯ ТОЧНОСТЬ: Используй ТОЛЬКО информацию, явно присутствующую в транскрипции. "
        "НЕ добавляй, НЕ домысливай, НЕ интерпретируй сверх сказанного\n"
        "- СОХРАНЕНИЕ КОНТЕКСТА: Фиксируй не только ЧТО было сказано, но и КАК обсуждалось "
        "(тон дискуссии, уровень согласия/несогласия, степень проработки вопроса)\n"
        "- ДЕТАЛИЗАЦИЯ БЕЗ ПОТЕРЬ: Если участник упомянул конкретный пример, цифру, дату, имя, "
        "технологию или любую специфическую деталь — это ОБЯЗАТЕЛЬНО должно быть в протоколе\n"
        "- АТРИБУЦИЯ ВЫСКАЗЫВАНИЙ: Если в транскрипции указаны имена участников, ВСЕГДА указывай, "
        "кто что сказал (например: \"Иван предложил...\", \"Мария отметила...\")\n"
        "- ОТКРЫТЫЕ ВОПРОСЫ: Фиксируй ВСЕ незакрытые вопросы, темы, требующие дополнительного обсуждения, "
        "и моменты неопределенности\n\n"
        
        "ПРАВИЛА ОБРАБОТКИ СПЕЦИФИЧЕСКОЙ ИНФОРМАЦИИ:\n"
        "- Ответственные лица: Указывай ТОЛЬКО если явно названы в транскрипции. "
        "Если сказано \"кто-то должен это сделать\" без имени — пиши \"не определен\" или \"Не указано\"\n"
        "- Сроки и даты: Указывай ТОЛЬКО если явно упомянуты. Если сказано \"скоро\" или \"в ближайшее время\" — "
        "сохраняй эту формулировку\n"
        "- Решения: Четко различай между \"принято решение\" и \"обсуждалась возможность\". "
        "Фиксируй уровень определенности\n"
        "- Цифры и метрики: Записывай все упомянутые числа, проценты, бюджеты, сроки точно как в транскрипции\n\n"
        
        "ПРИНЦИПЫ РАБОТЫ:\n"
        "1. ТОЧНОСТЬ: Используй только факты, явно присутствующие в стенограмме\n"
        "2. НЕТ ДОМЫСЛОВ: Не додумывай, не интерпретируй, не добавляй информацию от себя\n"
        "3. КОНТЕКСТ: Если упоминается роль/должность/срок/сумма — укажи их; если нет — не придумывай\n"
        "4. КРАТКОСТЬ: Излагай суть без воды, избегай избыточных деталей\n"
        "5. ТЕРМИНОЛОГИЯ: Сохраняй профессиональные термины и названия как в оригинале\n"
        "6. СТИЛЬ: Официально-деловой язык без разговорных оборотов\n\n"
        
        "🚨 КРИТИЧЕСКИ ВАЖНО - ФОРМАТ ИМЕН УЧАСТНИКОВ В ПРОТОКОЛЕ:\n"
        "В секции 'Участники' протокола используй имена в формате 'Имя Фамилия' БЕЗ отчества!\n"
        "Если предоставлен список участников - КОПИРУЙ имена ТОЧНО как они указаны в списке.\n\n"
        "❌ НЕПРАВИЛЬНО: только имя ('Софья', 'Галина') или с отчеством ('Софья Юрьевна Осипова')\n"
        "✅ ПРАВИЛЬНО: 'Софья Осипова', 'Галина Ямкина', 'Владимир Голиков'\n\n"
        "ОПРЕДЕЛЕНИЕ УЧАСТНИКОВ ИЗ ТРАНСКРИПЦИИ:\n"
        "⚠️ Если список участников не предоставлен явно:\n"
        "- Извлекай имена ТОЛЬКО из явных упоминаний в транскрипции\n"
        "- Источники: представления ('Меня зовут...'), обращения ('Света, как думаешь?')\n"
        "- Преобразуй уменьшительные в полные: Света→Светлана, Леша→Алексей\n"
        "- Используй формат 'Имя Фамилия' где возможно\n"
        "- ЕСЛИ имя не определить - оставляй метку спикера (SPEAKER_1, SPEAKER_2)\n"
        "- ❌ НЕ придумывай имена! НЕ используй 'Участник 1', 'Коллега'\n"
        "- ❌ НЕ дублируй: если Света = SPEAKER_1, не добавляй Светлану отдельно\n\n"
        
        "ФОРМАТИРОВАНИЕ ОБСУЖДЕНИЯ:\n"
        "Если группируешь обсуждение по темам/кластерам:\n"
        "- НЕ пиши слово 'Кластер', только название темы с маркером: '• **Название темы**'\n"
        "- Каждую идею/высказывание/позицию с новой строки\n"
        "- Формат высказывания: 'Имя Автора: текст' (без слова 'Идея', без скобок)\n"
        "- Между тематическими блоками оставляй пустую строку для визуального разделения\n\n"
        "Примеры:\n"
        "✅ ПРАВИЛЬНО:\n"
        "• **Архитектурные решения**\n\n"
        "Алексей Тимченко: предложил использовать микросервисную архитектуру\n\n"
        "Мария Иванова: поддержала, добавила про важность API gateway\n\n"
        "✗ НЕПРАВИЛЬНО:\n"
        "• Кластер «Архитектурные решения»: Идея (Алексей Тимченко): предложил...\n\n"
        
        "ЧТО ИГНОРИРОВАТЬ:\n"
        "- Междометия (э-э, м-м, ну, вот)\n"
        "- Повторы и запинки\n"
        "- Вводные фразы без смысловой нагрузки\n"
        "- Отвлеченные разговоры не по теме встречи\n\n"
        
        "ЧТО ВЫДЕЛЯТЬ:\n"
        "- Конкретные решения и резолюции\n"
        "- Поручения с указанием исполнителей (если упомянуты)\n"
        "- Сроки, суммы, показатели (только если явно названы)\n"
        "- Ключевые проблемы и их решения\n"
        "- Согласованные договоренности\n"
        "- Цифры, метрики, конкретные примеры (ОБЯЗАТЕЛЬНО включай все упомянутые)\n"
        "- Все темы обсуждения с указанием кто что сказал\n"
        "- Моменты несогласия, альтернативные мнения, нерешенные вопросы\n\n"
        
        "ФОРМАТ ВЫВОДА:\n"
        "Верни JSON в формате схемы. Если данные отсутствуют или неоднозначны — используй 'Не указано'.\n\n"
    )
    
    formatting_rules = (
        "КРИТИЧЕСКИ ВАЖНО — форматирование значений полей протокола:\n"
        "- ВСЕ значения полей должны быть ПРОСТЫМИ СТРОКАМИ (string), не объектами или массивами\n"
        "- НЕ используй вложенные объекты {} или массивы [] в качестве значений полей протокола\n"
        "- Списки форматируй как многострочный текст с маркерами '- ' (дефис + пробел)\n"
        "- Даты и время: простой текст, например '20 октября 2024, 14:30'\n"
        "- Участники: каждое имя с новой строки через \\n, БЕЗ ролей!, например 'Иван Петров\\nМария Сидорова\\nАлексей Смирнов'\n"
        "- Решения и задачи: многострочный текст со списком через \\n, каждый пункт с '- '\n\n"
        
        "ФОРМАТИРОВАНИЕ СПИСКОВ:\n"
        "- Внутри значений JSON полей: используй одинарный \\n для разделения элементов списка\n"
        "- Для визуального разделения тематических блоков в обсуждении: используй двойной \\n\\n\n\n"
        
        "ПРИМЕР ПРАВИЛЬНОГО JSON:\n"
        "{\n"
        '  "date": "20 октября 2024",\n'
        '  "time": "14:30",\n'
        '  "participants": "Оксана Иванова\\nГалина Петрова\\nАлексей Смирнов",\n'
        '  "decisions": "- Решение 1\\n- Решение 2\\n- Решение 3"\n'
        "}\n\n"
        
        "ПРИМЕР НЕПРАВИЛЬНОГО JSON (НЕ ДЕЛАЙ ТАК):\n"
        "{\n"
        '  "date": {"day": 20, "month": "октябрь"},  ❌ вложенный объект\n'
        '  "participants": ["Оксана", "Галя"],  ❌ массив\n'
        '  "decisions": [{"decision": "Решение 1"}]  ❌ массив объектов\n'
        "}"
    )
    
    return base_prompt + formatting_rules


def _build_user_prompt(
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    speaker_mapping: Optional[Dict[str, str]] = None,
    meeting_topic: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_time: Optional[str] = None,
    participants: Optional[List[Dict[str, str]]] = None,
    meeting_agenda: Optional[str] = None,
    project_list: Optional[str] = None,
) -> str:
    """
    Формирует пользовательский промпт с контекстом и требованиями к формату.
    
    ВАЖНО: Используется formatted_transcript из diarization_data, который:
    - Сохраняет последовательность чередования спикеров
    - Группирует только последовательные реплики одного спикера
    - Позволяет LLM понять динамику диалога
    - Экономит токены по сравнению с дублированием исходной транскрипции
    
    Исходная транскрипция не включается по умолчанию, но может быть добавлена
    через settings.include_raw_transcription_in_prompts для отладки проблем с диаризацией.
    """
    # Блок контекста (с учётом диаризации)
    if diarization_data and diarization_data.get("formatted_transcript"):
        transcription_text = (
            "Транскрипция с разделением говорящих:\n"
            f"{diarization_data['formatted_transcript']}\n\n"
            "Дополнительная информация:\n"
            f"- Количество говорящих: {diarization_data.get('total_speakers', 'неизвестно')}\n"
            f"- Список говорящих: {', '.join(diarization_data.get('speakers', []))}\n\n"
        )
        
        # Опционально добавляем исходную транскрипцию для отладки
        if settings.include_raw_transcription_in_prompts:
            transcription_text += (
                "\n═════════════════════════════════════════════════\n"
                "ИСХОДНАЯ ТРАНСКРИПЦИЯ (ДЛЯ ОТЛАДКИ):\n"
                "═════════════════════════════════════════════════\n\n"
                f"{transcription}\n\n"
            )
    else:
        transcription_text = (
            "Транскрипция:\n"
            f"{transcription}\n\n"
            "Примечание: Диаризация (разделение говорящих) недоступна для этой записи.\n"
        )
    
    # Добавляем информацию о сопоставлении спикеров с участниками
    participants_info = ""
    if speaker_mapping:
        mapping_list = "\n".join(f"- {sid} = {name}" for sid, name in speaker_mapping.items())
        participants_info = (
            f"\n\n{'═' * 63}\n"
            "УЧАСТНИКИ ВСТРЕЧИ (С РОЛЯМИ)\n"
            f"{'═' * 63}\n\n"
            "Сопоставление говорящих с участниками:\n"
            f"{mapping_list}\n\n"
            "⚠️ ИНСТРУКЦИИ ПО РАБОТЕ С УЧАСТНИКАМИ:\n"
            "1. Используй РЕАЛЬНЫЕ ИМЕНА вместо меток спикеров (SPEAKER_1 → Имя)\n"
            "2. При назначении ответственных учитывай контекст высказываний участников\n"
            "3. Формат ответственного: ТОЛЬКО ИМЯ, без роли в скобках\n"
            "   ✓ Правильно: 'Ответственный: Иван Петров'\n"
            "   ✗ Неправильно: 'Ответственный: Иван Петров (Менеджер)'\n"
            "📌 СОПОСТАВЛЕНИЕ ИМЕН:\n"
            "В транскрипции могут встречаться сокращенные/разговорные варианты имен.\n"
            "АВТОМАТИЧЕСКИ сопоставляй их с полными именами из списка выше:\n\n"
            "Примеры логики сопоставления (применяй ко ВСЕМ участникам):\n"
            "   • Уменьшительные: Света→Светлана, Леша→Алексей, Саша→Александр и т.д.\n"
            "   • По фамилии: Тимченко→Алексей Тимченко, Короткова→Светлана Короткова и т.д.\n"
            "   • Только имя: Алексей→Алексей Тимченко (если один такой в списке)\n\n"
            "   ⚡ НЕ ограничивайся примерами! Анализируй ВЕСЬ список участников выше.\n"
            "   ⚡ В финальном протоколе используй ПОЛНОЕ ИМЯ из списка участников!\n"
        )
    elif participants:
        # Если нет speaker_mapping, но есть список участников - показываем его
        from src.services.participants_service import participants_service
        # ВАЖНО: format_participants_for_llm преобразует имена в формат "Имя Фамилия" (без отчества)
        formatted_participants = participants_service.format_participants_for_llm(participants)
        
        participants_info = (
            f"\n\n{'═' * 63}\n"
            "🎯 ПОЛНЫЙ СПИСОК УЧАСТНИКОВ ВСТРЕЧИ (ОБЯЗАТЕЛЬНЫЙ К ИСПОЛЬЗОВАНИЮ)\n"
            f"{'═' * 63}\n\n"
            f"{formatted_participants}\n\n"
            "╔═══════════════════════════════════════════════════════════╗\n"
            "║  🚨 КРИТИЧЕСКИ ВАЖНО - СТРОГИЕ ПРАВИЛА ИСПОЛЬЗОВАНИЯ     ║\n"
            "╚═══════════════════════════════════════════════════════════╝\n\n"
            "1️⃣ ИСПОЛЬЗУЙ ТОЛЬКО ИМЕНА ИЗ СПИСКА ВЫШЕ!\n"
            "   ЗАПРЕЩЕНО добавлять участников, которых НЕТ в списке!\n"
            "   ❌ НЕПРАВИЛЬНО: 'Коллега из ОРТ', 'Коллеги из ERP', 'Команда'\n"
            "   ✅ ПРАВИЛЬНО: только конкретные имена из списка\n\n"
            "2️⃣ ФОРМАТ ИМЕН: 'Имя Фамилия' (БЕЗ отчества)!\n"
            "   ❌ НЕПРАВИЛЬНО: 'Софья' (только имя)\n"
            "   ❌ НЕПРАВИЛЬНО: 'Викулин' (только фамилия)\n"
            "   ❌ НЕПРАВИЛЬНО: 'Осипова Софья Юрьевна' (с отчеством)\n"
            "   ✅ ПРАВИЛЬНО: 'Софья Осипова', 'Галина Ямкина', 'Владимир Голиков'\n\n"
            "3️⃣ СОПОСТАВЛЕНИЕ СОКРАЩЕННЫХ ИМЕН:\n"
            "   В транскрипции упоминания могут быть сокращенными.\n"
            "   ОБЯЗАТЕЛЬНО найди в списке выше ПОЛНОЕ соответствие:\n\n"
            "   📋 ПРАВИЛА СОПОСТАВЛЕНИЯ:\n"
            "   • 'Света', 'Светочка' → найди 'Светлана' в списке → используй полное имя\n"
            "   • 'Леша', 'Алёша' → найди 'Алексей' в списке → используй полное имя\n"
            "   • 'Галя' → найди 'Галина' в списке → используй полное имя\n"
            "   • 'Володь', 'Вова' → найди 'Владимир' в списке → используй полное имя\n"
            "   • 'Стас' → найди 'Станислав' или 'Святослав' в списке\n"
            "   • 'Викулин', 'Тимченко' (фамилия) → найди в списке по фамилии\n"
            "   • 'Марат' (имя) → найди в списке по имени → используй полное имя\n\n"
            "4️⃣ ПРОВЕРКА ПЕРЕД ДОБАВЛЕНИЕМ В ПРОТОКОЛ:\n"
            "   Для КАЖДОГО участника из транскрипции:\n"
            "   ✓ Найди соответствие в списке выше\n"
            "   ✓ Используй ТОЧНОЕ написание из списка (Имя Фамилия)\n"
            "   ✓ Если не можешь определить конкретного человека - НЕ включай в протокол\n\n"
            "⚡ ВАЖНО: Проанализируй ВЕСЬ список участников выше!\n"
            "⚡ НЕ выдумывай имена! Используй ТОЛЬКО из списка!\n"
            "⚡ При малейшем сомнении - сопоставь с полным списком!\n\n"
        )
    else:
        # Нет ни speaker_mapping, ни participants - автоопределение из транскрипции
        participants_info = (
            f"\n\n{'═' * 63}\n"
            "⚙️ АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ УЧАСТНИКОВ ИЗ ТРАНСКРИПЦИИ\n"
            f"{'═' * 63}\n\n"
            "Список участников не предоставлен. Определи имена из транскрипции.\n\n"
            "📋 ПРАВИЛА ОПРЕДЕЛЕНИЯ:\n\n"
            "1️⃣ ИЩИ ЯВНЫЕ УПОМИНАНИЯ:\n"
            "   • Представления: 'Меня зовут Иван Петров', 'Я — Мария'\n"
            "   • Обращения: 'Света, как думаешь?', 'Петров, расскажи о задаче'\n"
            "   • Упоминания: 'Как сказал Иван...', 'Нужно уточнить у Марии'\n\n"
            "2️⃣ ФОРМАТ ИМЕН:\n"
            "   • Предпочтительно: 'Имя Фамилия' (БЕЗ отчества)\n"
            "   • Если известно только имя: 'Иван'\n"
            "   • Если известна только фамилия: 'Петров'\n"
            "   • Преобразуй уменьшительные: Света→Светлана, Леша→Алексей, Володя→Владимир\n\n"
            "3️⃣ СОПОСТАВЛЕНИЕ СО СПИКЕРАМИ:\n"
            "   • Сопоставь каждую метку (SPEAKER_1, SPEAKER_2...) с именем если возможно\n"
            "   • Если имя определить НЕВОЗМОЖНО - оставь метку спикера как есть\n"
            "   • Пример результата: 'Иван Петров\\nСПЕАКЕR_2\\nСветлана Короткова\\nСПЕАКЕR_4'\n\n"
            "4️⃣ СТРОГИЕ ЗАПРЕТЫ:\n"
            "   ❌ НЕ придумывай имена, которых НЕТ в транскрипции\n"
            "   ❌ НЕ используй 'Участник 1', 'Коллега', 'Человек А', 'Неизвестный'\n"
            "   ❌ НЕ дублируй: если Света = SPEAKER_1, не добавляй Светлану отдельно\n"
            "   ❌ НЕ заменяй SPEAKER_N на описания типа 'Руководитель встречи'\n\n"
            "💡 ПОДСКАЗКИ:\n"
            "   • Начало встречи - часто там представляются\n"
            "   • Обращения по имени - самый надежный признак\n"
            "   • Контекст: 'наш тимлид Алексей', 'менеджер Мария'\n"
            "   • Уверенности нет? → Оставь SPEAKER_N\n\n"
        )

    # Добавляем информацию о встрече
    meeting_info = ""
    if meeting_topic or meeting_date or meeting_time:
        meeting_info = "\n\n" + "═" * 63 + "\n"
        meeting_info += "ИНФОРМАЦИЯ О ВСТРЕЧЕ\n"
        meeting_info += "═" * 63 + "\n\n"

        if meeting_topic:
            meeting_info += f"📋 Тема: {meeting_topic}\n"
        if meeting_date:
            meeting_info += f"📅 Дата: {meeting_date}\n"
        if meeting_time:
            meeting_info += f"🕐 Время: {meeting_time}\n"
        meeting_info += "\n"


    
    # Блок дополнительного контекста (повестка, проекты)
    context_section = ""
    if meeting_agenda or project_list:
        context_info = {
            'meeting_agenda': meeting_agenda,
            'project_list': project_list
        }
        context_info = {k: v for k, v in context_info.items() if v}

        if context_info:
            context_section += "\n\n## ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ДЛЯ АНАЛИЗА\n\n"
            context_section += "Используй следующую информацию для более точного извлечения данных протокола:\n\n"

            for key, value in context_info.items():
                if key == 'meeting_agenda':
                    context_section += f"**Повестка встречи:**\n{value}\n\n"
                elif key == 'project_list':
                    context_section += f"**Список проектов:**\n{value}\n\n"

    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])

    # Основной пользовательский промпт
    user_prompt = (
        "═══════════════════════════════════════════════════════════\n"
        "ИСХОДНЫЕ ДАННЫЕ ДЛЯ АНАЛИЗА\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"{context_section}"
        f"{transcription_text}\n"
        f"{participants_info}"
        f"{meeting_info}"
        "═══════════════════════════════════════════════════════════\n"
        "ПОЛЯ ДЛЯ ИЗВЛЕЧЕНИЯ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"{variables_str}\n\n"
        "═══════════════════════════════════════════════════════════\n"
        "ИНСТРУКЦИИ ПО ИЗВЛЕЧЕНИЮ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        
        "📋 СТРУКТУРА ВЫВОДА:\n"
        "- Верни только валидный JSON-объект (без ```json, без markdown)\n"
        "- Используй СТРОГО эти ключи из списка полей\n"
        "- Сохраняй порядок ключей как в списке выше\n"
        "- Каждое значение — строка (UTF-8), БЕЗ вложенных объектов или массивов\n\n"
        
        "📝 ФОРМАТИРОВАНИЕ ТЕКСТА:\n"
        "- Для списков/перечислений: каждый пункт с новой строки, начинай с '- ' (дефис + пробел)\n"
        "- НЕ используй нумерацию (1. 2. 3.), только дефисы\n"
        "- НЕ ставь точку в конце пункта списка\n"
        "- Для имен/участников: разделяй точкой с запятой (;)\n"
        "- Для дат/времени: сохраняй формат как упомянут в тексте\n\n"
        
        "🎯 ИЗВЛЕЧЕНИЕ ДАННЫХ:\n"
        "- Используй ТОЛЬКО факты из транскрипции\n"
        "- Если информация упомянута с контекстом (роль, срок, сумма) — укажи полностью\n"
        "- Если данные отсутствуют, неоднозначны или неясны — пиши 'Не указано'\n"
        "- Убирай дубликаты, объединяй идентичные пункты\n"
        "- Сохраняй хронологию: порядок пунктов = порядок в тексте\n\n"
        
        "🔍 ОБРАБОТКА ИНФОРМАЦИИ О ГОВОРЯЩИХ:\n"
        "- Если доступна диаризация: используй метки 'Спикер 1:', 'Спикер 2:' и т.д.\n"
        "- Определяй ответственных за действия по контексту их высказываний\n"
        "- Указывай кто принял решение или взял на себя обязательство\n"
        "- Если известны имена участников — используй ИХ, а не метки спикеров\n"
        "- Формат задачи: 'Описание задачи — Ответственный: Имя Фамилия' (без роли!)\n"
        "- Формат решения: 'Решение. Инициатор: Имя Фамилия' (если важно кто принял)\n\n"
        
        "🧹 ЧТО ОТФИЛЬТРОВЫВАТЬ:\n"
        "- Междометия, запинки, повторы слов\n"
        "- Вводные фразы без смысловой нагрузки\n"
        "- Разговоры не по теме встречи\n"
        "- Технические комментарии ('не слышно', 'повторите' и т.д.)\n\n"
        
        "═══════════════════════════════════════════════════════════\n"
        "ПРИМЕРЫ ПРАВИЛЬНОГО ФОРМАТИРОВАНИЯ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        
        "✅ ПРАВИЛЬНО:\n"
        "{\n"
        "  \"participants\": \"Иван Иванов\\nМария Петрова\\nАлексей Сидоров\",\n"
        "  \"main_topic\": \"Планирование маркетинговой кампании на Q2 2024\",\n"
        "  \"decisions\": \"- Увеличить бюджет на digital-маркетинг на 30%\\n- Утвердить новую стратегию продвижения в социальных сетях\\n- Отложить запуск рекламы на ТВ до следующего квартала\",\n"
        "  \"action_items\": \"- Подготовить презентацию новой стратегии к 15 марта — Ответственный: Мария Петрова\\n- Согласовать бюджет с финансовым отделом — Ответственный: Иван Иванов\\n- Провести анализ конкурентов — Ответственный: Алексей Сидоров\",\n"
        "  \"deadlines\": \"- Презентация стратегии: 15 марта 2024\\n- Согласование бюджета: до конца текущей недели\\n- Анализ конкурентов: к следующему совещанию\",\n"
        "  \"issues\": \"- Недостаточный охват целевой аудитории текущими каналами\\n- Высокая стоимость привлечения клиента\\n- Необходимость обновления креативов\"\n"
        "}\n\n"
        "ОБРАТИТЕ ВНИМАНИЕ: В action_items указаны только ИМЕНА без ролей в скобках!\n\n"
        
        "❌ НЕПРАВИЛЬНО:\n"
        "{\n"
        "  \"participants\": [\"Иван\", \"Мария\"],  ❌ массив вместо строки\n"
        "  \"decisions\": \"1) Решение один 2) Решение два.\",  ❌ нумерация + точки\n"
        "  \"action_items\": \"Подготовить презентацию (Мария)\",  ❌ без дефиса, неправильный формат\n"
        "  \"deadlines\": \"Срочно, как можно быстрее\",  ❌ нет конкретики, хотя она могла быть\n"
        "  \"extra_field\": \"...\",  ❌ поле не из списка\n"
        "  \"budget\": \"50000 рублей (предположительно)\"  ❌ домыслы в скобках\n"
        "}\n\n"
        
        "═══════════════════════════════════════════════════════════\n"
        "СПЕЦИФИЧНЫЕ ПРАВИЛА ПО ТИПАМ ПОЛЕЙ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"{_build_field_specific_rules(template_variables)}\n\n"
        "═══════════════════════════════════════════════════════════\n\n"
        
        "НАЧИНАЙ АНАЛИЗ. Верни только JSON без дополнительных комментариев.\n"
    )
    return user_prompt


class OpenAIProvider(LLMProvider):
    """Провайдер для OpenAI GPT"""
    
    def __init__(self):
        self.client = None
        self.http_client = None
        if settings.openai_api_key:
            openai.api_key = settings.openai_api_key
            # Создаем HTTP клиент с настройками SSL и таймаутом из настроек
            import httpx
            self.http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                http_client=self.http_client
            )
    
    def is_available(self) -> bool:
        return self.client is not None and settings.openai_api_key is not None
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол используя OpenAI GPT (Двухэтапный процесс)"""
        if not self.is_available():
            raise ValueError("OpenAI API не настроен")

        # Извлекаем параметры из kwargs
        participants = kwargs.get('participants')
        meeting_metadata = {
            'meeting_topic': kwargs.get('meeting_topic', ''),
            'meeting_date': kwargs.get('meeting_date', ''),
            'meeting_time': kwargs.get('meeting_time', '')
        }

        # Подготовка данных для первого этапа (Анализ)
        # Используем formatted_transcript если есть, так как он содержит метки спикеров
        analysis_transcription = transcription
        if diarization_data and diarization_data.get("formatted_transcript"):
            analysis_transcription = diarization_data["formatted_transcript"]

        # Форматирование списка участников
        participants_list_str = "Не предоставлен"
        if participants:
            try:
                from src.services.participants_service import participants_service
                participants_list_str = participants_service.format_participants_for_llm(participants)
            except ImportError:
                participants_list_str = "\\n".join([f"- {p.get('name', 'Unknown')}" for p in participants])

        # Проверяем, предоставлен ли meeting_type из speaker_mapping_service
        provided_meeting_type = kwargs.get('meeting_type')
        provided_speaker_mapping = kwargs.get('speaker_mapping')

        # Определяем модель для использования (для обоих этапов)
        # Если передан openai_model_key, пытаемся найти соответствующую модель в настройках
        selected_model = settings.openai_model
        openai_model_key = kwargs.get('openai_model_key')
        
        if openai_model_key:
            try:
                preset = next((p for p in settings.openai_models if p.key == openai_model_key), None)
                if preset:
                    selected_model = preset.model
                    logger.info(f"Используется пользовательская модель: {selected_model} (ключ: {openai_model_key})")
            except Exception as e:
                logger.warning(f"Не удалось определить модель по ключу {openai_model_key}: {e}")
        
        if provided_meeting_type and provided_speaker_mapping:
            # ЭТАП 1 пропущен - используем данные из speaker_mapping_service
            logger.info(f"✅ ЭТАП 1 пропущен: тип встречи ({provided_meeting_type}) и сопоставление спикеров ({len(provided_speaker_mapping)} спикеров) уже определены")
            meeting_type = provided_meeting_type
            speaker_mapping = provided_speaker_mapping
        else:
            # ЭТАП 1: АНАЛИЗ (Тип встречи + Сопоставление спикеров)
            logger.info("🚀 Запуск ЭТАПА 1: Анализ встречи и сопоставление спикеров")
            
            analysis_system_prompt = build_analysis_system_prompt()
            analysis_user_prompt = build_analysis_prompt(
                transcription=analysis_transcription,
                participants_list=participants_list_str,
                meeting_metadata=meeting_metadata,
                # Extract context parameters from kwargs
                meeting_agenda=kwargs.get('meeting_agenda'),
                project_list=kwargs.get('project_list')
            )

            analysis_result = await self._call_openai(
                system_prompt=analysis_system_prompt,
                user_prompt=analysis_user_prompt,
                schema=MEETING_ANALYSIS_SCHEMA,
                step_name="Analysis",
                model=selected_model
            )

            meeting_type = analysis_result.get('meeting_type', 'general')
            speaker_mapping = analysis_result.get('speaker_mappings', {})
            
            logger.info(f"✅ ЭТАП 1 завершен. Тип: {meeting_type}, Спикеров сопоставлено: {len(speaker_mapping)}")

        # ЭТАП 2: ГЕНЕРАЦИЯ (Извлечение данных протокола)
        logger.info("🚀 Запуск ЭТАПА 2: Генерация протокола")

        generation_system_prompt = build_generation_system_prompt()
        generation_user_prompt = build_generation_prompt(
            transcription=analysis_transcription, # Используем ту же транскрипцию с метками
            template_variables=template_variables,
            speaker_mapping=speaker_mapping,
            meeting_type=meeting_type,
            # Extract context parameters from kwargs
            meeting_agenda=kwargs.get('meeting_agenda'),
            project_list=kwargs.get('project_list')
        )

        generation_result = await self._call_openai(
            system_prompt=generation_system_prompt,
            user_prompt=generation_user_prompt,
            schema=PROTOCOL_DATA_SCHEMA,
            step_name="Generation",
            model=selected_model
        )

        protocol_data = generation_result.get('protocol_data', {})
        
        logger.info(f"✅ ЭТАП 2 завершен. Извлечено полей: {len(protocol_data)}")

        # Консолидация результатов
        # Возвращаем плоский словарь, как ожидает остальная система
        # Но добавляем метаданные анализа
        final_result = protocol_data.copy()
        final_result['_meeting_type'] = meeting_type
        final_result['_speaker_mapping'] = speaker_mapping
        final_result['_analysis_confidence'] = 0.0 if provided_meeting_type else analysis_result.get('analysis_confidence', 0.0)
        final_result['_quality_score'] = generation_result.get('quality_score', 0.0)

        return final_result

    async def _call_openai(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], step_name: str, model: str = None) -> Dict[str, Any]:
        """Вспомогательный метод для вызова OpenAI"""
        
        selected_model = model or settings.openai_model
        # Для анализа можно использовать модель попроще/быстрее, но пока используем основную
        
        extra_headers = {}
        if settings.http_referer:
            extra_headers["HTTP-Referer"] = settings.http_referer
        if settings.x_title:
            extra_headers["X-Title"] = settings.x_title

        logger.info(f"Отправляем запрос в OpenAI [{step_name}] с моделью {selected_model}")

        async def _api_call():
            return await asyncio.to_thread(
                self.client.chat.completions.create,
                model=selected_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_schema", "json_schema": schema},
                extra_headers=extra_headers
            )

        try:
            response = await _api_call()
            content = response.choices[0].message.content
            
            # Логирование кешированных токенов
            if settings.log_cache_metrics:
                log_cached_tokens_usage(
                    response=response,
                    context=f"generate_protocol_{step_name}",
                    model_name=selected_model,
                    provider="openai"
                )
                
            return safe_json_parse(content, context=f"OpenAI {step_name} response")
            
        except Exception as e:
            logger.error(f"Ошибка при вызове OpenAI [{step_name}]: {e}")
            raise


class AnthropicProvider(LLMProvider):
    """Провайдер для Anthropic Claude"""
    
    def __init__(self):
        self.client = None
        if settings.anthropic_api_key:
            # Создаем HTTP клиент с настройками SSL и таймаутом из настроек
            import httpx
            http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.client = Anthropic(
                api_key=settings.anthropic_api_key,
                http_client=http_client
            )
    
    def is_available(self) -> bool:
        return self.client is not None and settings.anthropic_api_key is not None
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол используя Anthropic Claude (Двухэтапный процесс)"""
        if not self.is_available():
            raise ValueError("Anthropic API не настроен")

        # Извлекаем параметры из kwargs
        participants = kwargs.get('participants')
        meeting_metadata = {
            'meeting_topic': kwargs.get('meeting_topic', ''),
            'meeting_date': kwargs.get('meeting_date', ''),
            'meeting_time': kwargs.get('meeting_time', '')
        }

        # Подготовка данных для первого этапа (Анализ)
        analysis_transcription = transcription
        if diarization_data and diarization_data.get("formatted_transcript"):
            analysis_transcription = diarization_data["formatted_transcript"]

        # Форматирование списка участников
        participants_list_str = "Не предоставлен"
        if participants:
            try:
                from src.services.participants_service import participants_service
                participants_list_str = participants_service.format_participants_for_llm(participants)
            except ImportError:
                participants_list_str = "\\n".join([f"- {p.get('name', 'Unknown')}" for p in participants])

        # Проверяем, предоставлен ли meeting_type из speaker_mapping_service
        provided_meeting_type = kwargs.get('meeting_type')
        provided_speaker_mapping = kwargs.get('speaker_mapping')
        
        if provided_meeting_type and provided_speaker_mapping:
            # ЭТАП 1 пропущен - используем данные из speaker_mapping_service
            logger.info(f"✅ [Anthropic] ЭТАП 1 пропущен: тип встречи ({provided_meeting_type}) и сопоставление спикеров ({len(provided_speaker_mapping)} спикеров) уже определены")
            meeting_type = provided_meeting_type
            speaker_mapping = provided_speaker_mapping
        else:
            # ЭТАП 1: АНАЛИЗ
            logger.info("🚀 [Anthropic] Запуск ЭТАПА 1: Анализ встречи")
            
            analysis_system_prompt = build_analysis_system_prompt()
            analysis_user_prompt = build_analysis_prompt(
                transcription=analysis_transcription,
                participants_list=participants_list_str,
                meeting_metadata=meeting_metadata,
                # Extract context parameters from kwargs
                meeting_agenda=kwargs.get('meeting_agenda'),
                project_list=kwargs.get('project_list')
            )

            # Используем prompt caching для первого этапа (где большая транскрипция)
            analysis_result = await self._call_anthropic(
                system_prompt=analysis_system_prompt,
                user_prompt=analysis_user_prompt,
                step_name="Analysis",
                use_caching=True,
                transcription_for_caching=analysis_transcription
            )

            meeting_type = analysis_result.get('meeting_type', 'general')
            speaker_mapping = analysis_result.get('speaker_mappings', {})
            
            logger.info(f"✅ [Anthropic] ЭТАП 1 завершен. Тип: {meeting_type}")

        # ЭТАП 2: ГЕНЕРАЦИЯ
        logger.info("🚀 [Anthropic] Запуск ЭТАПА 2: Генерация протокола")

        generation_system_prompt = build_generation_system_prompt()
        generation_user_prompt = build_generation_prompt(
            transcription=analysis_transcription,
            template_variables=template_variables,
            speaker_mapping=speaker_mapping,
            meeting_type=meeting_type,
            meeting_agenda=kwargs.get('meeting_agenda'),
            project_list=kwargs.get('project_list')
        )

        # Тоже используем caching, так как транскрипция та же
        generation_result = await self._call_anthropic(
            system_prompt=generation_system_prompt,
            user_prompt=generation_user_prompt,
            step_name="Generation",
            use_caching=True,
            transcription_for_caching=analysis_transcription
        )

        protocol_data = generation_result.get('protocol_data', {})
        
        logger.info(f"✅ [Anthropic] ЭТАП 2 завершен.")

        # Консолидация
        final_result = protocol_data.copy()
        final_result['_meeting_type'] = meeting_type
        final_result['_speaker_mapping'] = speaker_mapping
        final_result['_analysis_confidence'] = analysis_result.get('analysis_confidence', 0.0)
        final_result['_quality_score'] = generation_result.get('quality_score', 0.0)

        return final_result

    async def _call_anthropic(self, system_prompt: str, user_prompt: str, step_name: str, use_caching: bool = False, transcription_for_caching: str = "") -> Dict[str, Any]:
        """Вспомогательный метод для вызова Anthropic"""
        
        extra_headers = {}
        if settings.http_referer:
            extra_headers["HTTP-Referer"] = settings.http_referer
        if settings.x_title:
            extra_headers["X-Title"] = settings.x_title

        # Подготовка сообщений с учетом кеширования
        system_block = system_prompt
        messages = [{"role": "user", "content": user_prompt}]

        if use_caching and settings.enable_prompt_caching and len(transcription_for_caching) >= settings.min_transcription_length_for_cache:
            logger.debug(f"Используем Anthropic prompt caching для {step_name}")
            system_block, messages = build_anthropic_messages_with_caching(
                system_prompt, transcription_for_caching, user_prompt
            )

        async def _api_call():
            return await asyncio.to_thread(
                self.client.messages.create,
                model="claude-3-haiku-20240307",
                max_tokens=4000,
                temperature=0.1,
                system=system_block,
                messages=messages,
                extra_headers=extra_headers
            )

        try:
            response = await _api_call()
            content = response.content[0].text
            
            if settings.log_cache_metrics:
                log_cached_tokens_usage(
                    response=response,
                    context=f"Anthropic_{step_name}",
                    model_name="claude-3-haiku-20240307",
                    provider="anthropic"
                )
                
            return safe_json_parse(content, context=f"Anthropic {step_name} response")
            
        except Exception as e:
            logger.error(f"Ошибка при вызове Anthropic [{step_name}]: {e}")
            raise


class YandexGPTProvider(LLMProvider):
    """Провайдер для Yandex GPT"""
    
    def __init__(self):
        self.api_key = settings.yandex_api_key
        self.folder_id = settings.yandex_folder_id
    
    def is_available(self) -> bool:
        return self.api_key is not None and self.folder_id is not None
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол используя Yandex GPT"""
        if not self.is_available():
            raise ValueError("Yandex GPT API не настроен")

        # Извлекаем параметры из kwargs
        speaker_mapping = kwargs.get('speaker_mapping')
        meeting_topic = kwargs.get('meeting_topic')
        meeting_date = kwargs.get('meeting_date')
        meeting_time = kwargs.get('meeting_time')
        participants = kwargs.get('participants')
        meeting_agenda = kwargs.get('meeting_agenda')
        project_list = kwargs.get('project_list')

        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()

        prompt = _build_user_prompt(
            transcription,
            template_variables,
            diarization_data,
            speaker_mapping,
            meeting_topic,
            meeting_date,
            meeting_time,
            participants,
            meeting_agenda,
            project_list
        )
        
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json"
        }
        
        if settings.http_referer:
            headers["Referer"] = settings.http_referer
        if settings.x_title:
            headers["X-Title"] = settings.x_title
        
        data = {
            "modelUri": f"gpt://{self.folder_id}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.1,
                "maxTokens": 2000
            },
            "messages": [
                {
                    "role": "system",
                    "text": system_prompt
                },
                {
                    "role": "user", 
                    "text": prompt
                }
            ]
        }
        
        try:
            async with httpx.AsyncClient(verify=settings.ssl_verify) as client:
                response = await client.post(
                    "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                    headers=headers,
                    json=data,
                    timeout=settings.llm_timeout_seconds
                )
                response.raise_for_status()
                
                result = response.json()
                content = result["result"]["alternatives"][0]["message"]["text"]
                logger.info(f"Получен ответ от Yandex GPT (длина: {len(content) if content else 0}): {content[:200] if content else 'None'}...")
                
                # Используем безопасный парсер JSON
                return safe_json_parse(content, context="Yandex GPT API response")
                
        except Exception as e:
            logger.error(f"Ошибка при работе с Yandex GPT API: {e}")
            raise


class LLMManager:
    """Менеджер для работы с различными LLM провайдерами"""
    
    def __init__(self):
        self.providers = {
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "yandex": YandexGPTProvider()
        }
    
    def get_available_providers(self) -> Dict[str, str]:
        """Получить список доступных провайдеров"""
        available = {}
        provider_names = {
            "openai": "OpenAI GPT",
            "anthropic": "Anthropic Claude",
            "yandex": "Yandex GPT"
        }
        
        for key, provider in self.providers.items():
            if provider.is_available():
                available[key] = provider_names[key]
        
        return available
    
    async def generate_protocol(self, provider_name: str, transcription: str, 
                              template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол используя указанного провайдера"""
        if provider_name not in self.providers:
            raise ValueError(f"Неизвестный провайдер: {provider_name}")
        
        provider = self.providers[provider_name]
        if not provider.is_available():
            raise ValueError(f"Провайдер {provider_name} недоступен")
        
        # Передаем дополнительные аргументы (например, openai_model_key)
        return await provider.generate_protocol(transcription, template_variables, diarization_data, **kwargs)
    
    async def generate_protocol_with_fallback(self, preferred_provider: str, transcription: str, 
                                            template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол с переключением на резервный провайдер в случае ошибки"""
        available_providers = list(self.get_available_providers().keys())
        
        if not available_providers:
            raise ValueError("Нет доступных LLM провайдеров")
        
        # Сначала пробуем предпочитаемый провайдер
        providers_to_try = [preferred_provider] if preferred_provider in available_providers else []
        # Добавляем остальные провайдеры как резервные
        for provider in available_providers:
            if provider not in providers_to_try:
                providers_to_try.append(provider)
        
        last_error = None
        for provider_name in providers_to_try:
            try:
                logger.info(f"Попытка генерации протокола с провайдером: {provider_name}")
                result = await self.generate_protocol(provider_name, transcription, template_variables, diarization_data, **kwargs)
                logger.info(f"Успешно сгенерирован протокол с провайдером: {provider_name}")
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"Ошибка с провайдером {provider_name}: {e}")
                continue
        
        # Если все провайдеры не сработали
        raise ValueError(f"Все доступные провайдеры не сработали. Последняя ошибка: {last_error}")

async def generate_protocol(
    manager: 'LLMManager',
    provider_name: str,
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    diarization_analysis: Optional[Dict[str, Any]] = None,
    participants_list: Optional[str] = None,
    meeting_metadata: Optional[Dict[str, str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Консолидированный метод генерации протокола: 2 запроса вместо 5-6
    Запрос 1: Сопоставление спикеров + извлечение структуры
    Запрос 2: Финальная генерация протокола + QA

    Args:
        manager: Менеджер LLM
        provider_name: Название провайдера
        transcription: Текст транскрипции
        template_variables: Переменные шаблона
        diarization_data: Данные диаризации
        diarization_analysis: Анализ диаризации
        participants_list: Список участников
        meeting_metadata: Метаданные встречи
        **kwargs: Дополнительные параметры

    Returns:
        Финальный протокол
    """
    """
    Генерировать протокол (обертка над менеджером)
    """
    # Подготавливаем аргументы для передачи в менеджер
    # Preserve original participants if it exists
    original_participants = kwargs.get('participants')
    
    call_kwargs = kwargs.copy()
    
    # Передаем список участников
    if participants_list:
        # Only set if not already present or if original was None
        if 'participants' not in call_kwargs:
            call_kwargs['participants'] = participants_list
        
    # Передаем метаданные встречи
    if meeting_metadata:
        call_kwargs.update(meeting_metadata)
        
    # Передаем анализ диаризации если есть
    if diarization_analysis:
        call_kwargs['diarization_analysis'] = diarization_analysis

    # Restore original participants if it was present, ensuring it takes precedence
    if original_participants is not None:
        call_kwargs['participants'] = original_participants

    return await manager.generate_protocol(
        provider_name=provider_name,
        transcription=transcription,
        template_variables=template_variables,
        diarization_data=diarization_data,
        **call_kwargs
    )


# Глобальный экземпляр менеджера LLM
llm_manager = LLMManager()
