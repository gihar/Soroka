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

# Импорт для контекстно-зависимых промптов
from src.services.meeting_classifier import meeting_classifier
from src.prompts.specialized_prompts import (
    get_specialized_system_prompt, 
    get_specialized_extraction_instructions
)

# Импорт для retry логики
from src.reliability.retry import RetryManager, LLM_RETRY_CONFIG

# Импорт исключений
from src.exceptions.processing import LLMInsufficientCreditsError

if TYPE_CHECKING:
    from src.services.segmentation_service import TranscriptionSegment


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
    diarization_analysis: Optional[Dict[str, Any]] = None
) -> str:
    """
    Строгая системная политика для получения профессионального протокола.
    Автоматически выбирает специализированный промпт если включена классификация.
    
    Args:
        transcription: Текст транскрипции (для классификации)
        diarization_analysis: Анализ диаризации (для классификации)
        
    Returns:
        Системный промпт (базовый или специализированный)
    """
    # Если включена классификация и есть транскрипция
    if settings.meeting_type_detection and transcription:
        try:
            # Классифицируем встречу
            meeting_type, _ = meeting_classifier.classify(
                transcription, 
                diarization_analysis
            )
            
            # Получаем специализированный промпт
            specialized_prompt = get_specialized_system_prompt(meeting_type)
            logger.info(f"Использую специализированный промпт для типа встречи: {meeting_type}")
            return specialized_prompt
            
        except Exception as e:
            logger.warning(f"Ошибка при классификации встречи: {e}. Используем базовый промпт")
    
    # Базовый промпт (для общих встреч или при отключенной классификации)
    return (
        "Ты — профессиональный протоколист высшей квалификации с опытом документирования "
        "деловых встреч, совещаний и переговоров.\n\n"
        
        "ТВОЯ РОЛЬ:\n"
        "- Извлекать и структурировать ключевую информацию из стенограмм встреч\n"
        "- Создавать четкие, лаконичные и информативные протоколы\n"
        "- Сохранять объективность и фактологическую точность\n\n"
        
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
        "- ❌ НЕ придумывай имена! НЕ используй 'Участник 1', 'Коллега'\n\n"
        "СОПОСТАВЛЕНИЕ ИМЕН ИЗ ТРАНСКРИПЦИИ:\n"
        "В транскрипции люди говорят сокращенно/неполно. Твоя задача - найти\n"
        "соответствие в списке участников и использовать ПОЛНОЕ ИМЯ в формате 'Имя Фамилия'.\n\n"
        "Принципы сопоставления (применяй ко ВСЕМ участникам):\n\n"
        "1. УМЕНЬШИТЕЛЬНЫЕ ИМЕНА:\n"
        "   - Света, Светочка → ищи 'Светлана' в списке → используй 'Светлана Фамилия'\n"
        "   - Леша, Лёша, Алёша → ищи 'Алексей' → используй 'Алексей Фамилия'\n"
        "   - Саша → ищи 'Александр' или 'Александра'\n"
        "   - Женя → ищи 'Евгений' или 'Евгения'\n"
        "   - Коля → ищи 'Николай'\n"
        "   - Дима → ищи 'Дмитрий'\n"
        "   ⚡ Это ПРИМЕРЫ логики! Применяй такой же подход для ЛЮБЫХ уменьшительных имен\n\n"
        "2. УПОМИНАНИЕ ПО ФАМИЛИИ:\n"
        "   - Если упомянута только фамилия → найди полное имя в списке участников\n"
        "   - Пример: 'Тимченко' в транскрипции → 'Алексей Тимченко' из списка\n"
        "   - Пример: 'Короткова' в транскрипции → 'Светлана Короткова' из списка\n"
        "   ⚡ Работает для ВСЕХ фамилий из списка участников\n\n"
        "3. УПОМИНАНИЕ ТОЛЬКО ИМЕНИ:\n"
        "   - Если в транскрипции только имя → дополни фамилией из списка участников\n"
        "   - Пример: 'Алексей' в транскрипции → 'Алексей Тимченко' из списка\n"
        "   - Используй контекст для сопоставления при неоднозначности\n"
        "   ⚡ Анализируй ВЕСЬ список участников для сопоставления\n\n"
        "4. ВАЖНО:\n"
        "   - В финальном протоколе ВСЕГДА используй ПОЛНОЕ ИМЯ из списка участников\n"
        "   - Примеры выше показывают ЛОГИКУ - применяй её ко ВСЕМ участникам\n"
        "   - НЕ ограничивайся только примерами - работай со ВСЕМИ участниками из списка\n"
        "   - При неоднозначности выбирай наиболее вероятный вариант по контексту\n\n"
        
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
        "- Согласованные договоренности\n\n"
        
        "ФОРМАТ ВЫВОДА:\n"
        "Строго валидный JSON-объект без обрамления в markdown, без комментариев, без пояснений. "
        "Если данные отсутствуют или неоднозначны — используй 'Не указано'.\n\n"
        
        "КРИТИЧЕСКИ ВАЖНО — форматирование значений:\n"
        "- ВСЕ значения в JSON должны быть ПРОСТЫМИ СТРОКАМИ (string)\n"
        "- НЕ используй вложенные объекты {} или массивы [] в качестве значений полей\n"
        "- Списки форматируй как многострочный текст с маркерами '- ' (дефис + пробел)\n"
        "- Даты и время: простой текст, например '20 октября 2024, 14:30'\n"
        "- Участники: каждое имя с новой строки через \\n, БЕЗ ролей!, например 'Иван Петров\\nМария Сидорова\\nАлексей Смирнов'\n"
        "- Решения и задачи: многострочный текст со списком через \\n, каждый пункт с '- '\n\n"
        
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


def _build_user_prompt(
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    speaker_mapping: Optional[Dict[str, str]] = None,
    meeting_topic: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_time: Optional[str] = None,
    participants: Optional[List[Dict[str, str]]] = None,
    meeting_structure = None,  # MeetingStructure, но избегаем circular import
) -> str:
    """Формирует пользовательский промпт с контекстом и требованиями к формату."""
    # Блок контекста (с учётом диаризации)
    if diarization_data and diarization_data.get("formatted_transcript"):
        transcription_text = (
            "Транскрипция с разделением говорящих:\n"
            f"{diarization_data['formatted_transcript']}\n\n"
            "Дополнительная информация:\n"
            f"- Количество говорящих: {diarization_data.get('total_speakers', 'неизвестно')}\n"
            f"- Список говорящих: {', '.join(diarization_data.get('speakers', []))}\n\n"
            "Исходная транскрипция (для справки):\n"
            f"{transcription}\n"
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
        participants_info = "\n\n" + "═" * 63 + "\n"
        participants_info += "УЧАСТНИКИ ВСТРЕЧИ (С РОЛЯМИ)\n"
        participants_info += "═" * 63 + "\n\n"
        participants_info += "Сопоставление говорящих с участниками:\n"
        for speaker_id, participant_name in speaker_mapping.items():
            participants_info += f"- {speaker_id} = {participant_name}\n"
        participants_info += "\n"
        participants_info += "⚠️ ИНСТРУКЦИИ ПО РАБОТЕ С УЧАСТНИКАМИ:\n"
        participants_info += "1. Используй РЕАЛЬНЫЕ ИМЕНА вместо меток спикеров (SPEAKER_1 → Имя)\n"
        participants_info += "2. При назначении ответственных учитывай контекст высказываний участников\n"
        participants_info += "3. Формат ответственного: ТОЛЬКО ИМЯ, без роли в скобках\n"
        participants_info += "   ✓ Правильно: 'Ответственный: Иван Петров'\n"
        participants_info += "   ✗ Неправильно: 'Ответственный: Иван Петров (Менеджер)'\n"
        participants_info += "📌 СОПОСТАВЛЕНИЕ ИМЕН:\n"
        participants_info += "В транскрипции могут встречаться сокращенные/разговорные варианты имен.\n"
        participants_info += "АВТОМАТИЧЕСКИ сопоставляй их с полными именами из списка выше:\n\n"
        participants_info += "Примеры логики сопоставления (применяй ко ВСЕМ участникам):\n"
        participants_info += "   • Уменьшительные: Света→Светлана, Леша→Алексей, Саша→Александр и т.д.\n"
        participants_info += "   • По фамилии: Тимченко→Алексей Тимченко, Короткова→Светлана Короткова и т.д.\n"
        participants_info += "   • Только имя: Алексей→Алексей Тимченко (если один такой в списке)\n\n"
        participants_info += "   ⚡ НЕ ограничивайся примерами! Анализируй ВЕСЬ список участников выше.\n"
        participants_info += "   ⚡ В финальном протоколе используй ПОЛНОЕ ИМЯ из списка участников!\n"
    elif participants:
        # Если нет speaker_mapping, но есть список участников - показываем его
        participants_info = "\n\n" + "═" * 63 + "\n"
        participants_info += "🎯 ПОЛНЫЙ СПИСОК УЧАСТНИКОВ ВСТРЕЧИ (ОБЯЗАТЕЛЬНЫЙ К ИСПОЛЬЗОВАНИЮ)\n"
        participants_info += "═" * 63 + "\n\n"
        from src.services.participants_service import participants_service
        participants_info += participants_service.format_participants_for_llm(participants)
        participants_info += "\n\n"
        participants_info += "╔═══════════════════════════════════════════════════════════╗\n"
        participants_info += "║  🚨 КРИТИЧЕСКИ ВАЖНО - СТРОГИЕ ПРАВИЛА ИСПОЛЬЗОВАНИЯ     ║\n"
        participants_info += "╚═══════════════════════════════════════════════════════════╝\n\n"
        participants_info += "1️⃣ ИСПОЛЬЗУЙ ТОЛЬКО ИМЕНА ИЗ СПИСКА ВЫШЕ!\n"
        participants_info += "   ЗАПРЕЩЕНО добавлять участников, которых НЕТ в списке!\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Коллега из ОРТ', 'Коллеги из ERP', 'Команда'\n"
        participants_info += "   ✅ ПРАВИЛЬНО: только конкретные имена из списка\n\n"
        participants_info += "2️⃣ ФОРМАТ ИМЕН: 'Имя Фамилия' (БЕЗ отчества)!\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Софья' (только имя)\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Викулин' (только фамилия)\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Осипова Софья Юрьевна' (с отчеством)\n"
        participants_info += "   ✅ ПРАВИЛЬНО: 'Софья Осипова', 'Галина Ямкина', 'Владимир Голиков'\n\n"
        participants_info += "3️⃣ СОПОСТАВЛЕНИЕ СОКРАЩЕННЫХ ИМЕН:\n"
        participants_info += "   В транскрипции упоминания могут быть сокращенными.\n"
        participants_info += "   ОБЯЗАТЕЛЬНО найди в списке выше ПОЛНОЕ соответствие:\n\n"
        participants_info += "   📋 ПРАВИЛА СОПОСТАВЛЕНИЯ:\n"
        participants_info += "   • 'Света', 'Светочка' → найди 'Светлана' в списке → используй полное имя\n"
        participants_info += "   • 'Леша', 'Алёша' → найди 'Алексей' в списке → используй полное имя\n"
        participants_info += "   • 'Галя' → найди 'Галина' в списке → используй полное имя\n"
        participants_info += "   • 'Володь', 'Вова' → найди 'Владимир' в списке → используй полное имя\n"
        participants_info += "   • 'Стас' → найди 'Станислав' или 'Святослав' в списке\n"
        participants_info += "   • 'Викулин', 'Тимченко' (фамилия) → найди в списке по фамилии\n"
        participants_info += "   • 'Марат' (имя) → найди в списке по имени → используй полное имя\n\n"
        participants_info += "4️⃣ ПРОВЕРКА ПЕРЕД ДОБАВЛЕНИЕМ В ПРОТОКОЛ:\n"
        participants_info += "   Для КАЖДОГО участника из транскрипции:\n"
        participants_info += "   ✓ Найди соответствие в списке выше\n"
        participants_info += "   ✓ Используй ТОЧНОЕ написание из списка (Имя Фамилия)\n"
        participants_info += "   ✓ Если не можешь определить конкретного человека - НЕ включай в протокол\n\n"
        participants_info += "⚡ ВАЖНО: Проанализируй ВЕСЬ список участников выше!\n"
        participants_info += "⚡ НЕ выдумывай имена! Используй ТОЛЬКО из списка!\n"
        participants_info += "⚡ При малейшем сомнении - сопоставь с полным списком!\n\n"
    else:
        # Нет ни speaker_mapping, ни participants - автоопределение из транскрипции
        participants_info = "\n\n" + "═" * 63 + "\n"
        participants_info += "⚙️ АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ УЧАСТНИКОВ ИЗ ТРАНСКРИПЦИИ\n"
        participants_info += "═" * 63 + "\n\n"
        participants_info += "Список участников не предоставлен. Определи имена из транскрипции.\n\n"
        participants_info += "📋 ПРАВИЛА ОПРЕДЕЛЕНИЯ:\n\n"
        participants_info += "1️⃣ ИЩИ ЯВНЫЕ УПОМИНАНИЯ:\n"
        participants_info += "   • Представления: 'Меня зовут Иван Петров', 'Я — Мария'\n"
        participants_info += "   • Обращения: 'Света, как думаешь?', 'Петров, расскажи о задаче'\n"
        participants_info += "   • Упоминания: 'Как сказал Иван...', 'Нужно уточнить у Марии'\n\n"
        participants_info += "2️⃣ ФОРМАТ ИМЕН:\n"
        participants_info += "   • Предпочтительно: 'Имя Фамилия' (БЕЗ отчества)\n"
        participants_info += "   • Если известно только имя: 'Иван'\n"
        participants_info += "   • Если известна только фамилия: 'Петров'\n"
        participants_info += "   • Преобразуй уменьшительные: Света→Светлана, Леша→Алексей, Володя→Владимир\n\n"
        participants_info += "3️⃣ СОПОСТАВЛЕНИЕ СО СПИКЕРАМИ:\n"
        participants_info += "   • Сопоставь каждую метку (SPEAKER_1, SPEAKER_2...) с именем если возможно\n"
        participants_info += "   • Если имя определить НЕВОЗМОЖНО - оставь метку спикера как есть\n"
        participants_info += "   • Пример результата: 'Иван Петров\\nСПЕАКЕR_2\\nСветлана Короткова\\nСПЕАКЕR_4'\n\n"
        participants_info += "4️⃣ СТРОГИЕ ЗАПРЕТЫ:\n"
        participants_info += "   ❌ НЕ придумывай имена, которых НЕТ в транскрипции\n"
        participants_info += "   ❌ НЕ используй 'Участник 1', 'Коллега', 'Человек А', 'Неизвестный'\n"
        participants_info += "   ❌ НЕ дублируй: если Света = SPEAKER_1, не добавляй Светлану отдельно\n"
        participants_info += "   ❌ НЕ заменяй SPEAKER_N на описания типа 'Руководитель встречи'\n\n"
        participants_info += "💡 ПОДСКАЗКИ:\n"
        participants_info += "   • Начало встречи - часто там представляются\n"
        participants_info += "   • Обращения по имени - самый надежный признак\n"
        participants_info += "   • Контекст: 'наш тимлид Алексей', 'менеджер Мария'\n"
        participants_info += "   • Уверенности нет? → Оставь SPEAKER_N\n\n"

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

    # Добавляем структурный анализ если доступен
    structure_info = ""
    if meeting_structure:
        structure_text = meeting_structure.format_for_llm_prompt()
        if structure_text:
            structure_info = structure_text
    
    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])

    # Основной пользовательский промпт
    user_prompt = (
        "═══════════════════════════════════════════════════════════\n"
        "ИСХОДНЫЕ ДАННЫЕ ДЛЯ АНАЛИЗА\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"{transcription_text}\n"
        f"{structure_info}"
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
        
        "👥 Участники (participants):\n"
        "- Формат: каждое имя с новой строки через \\n\n"
        "- Пример: 'Имя Фамилия\\nИмя2 Фамилия2\\nИмя3 Фамилия3'\n"
        "- БЕЗ ролей и должностей в списке участников!\n"
        "- Если имена не упомянуты: 'Спикер 1\\nСпикер 2\\nСпикер 3'\n\n"
        
        "📌 Решения (decisions):\n"
        "- Только согласованные, утвержденные решения\n"
        "- Формулировка должна отражать суть без лишних слов\n"
        "- Если есть условия — укажи их коротко\n\n"
        
        "✅ Задачи/поручения (action_items):\n"
        "- Формат: '- Описание задачи — Ответственный: [имя/роль/Спикер N]'\n"
        "- Если ответственный не назван явно, но понятен из контекста — укажи\n"
        "- Если непонятно кто ответственный: '- Описание задачи — Ответственный: Не указано'\n\n"
        
        "⏰ Сроки (deadlines):\n"
        "- Формат: '- Задача/событие: конкретный срок'\n"
        "- Сохраняй формат дат как в оригинале\n"
        "- Относительные сроки: 'к концу недели', 'к следующей встрече'\n\n"
        
        "⚠️ Проблемы/вопросы (issues/questions):\n"
        "- Формулируй суть проблемы кратко\n"
        "- Убирай эмоциональную окраску, оставляй факты\n"
        "- Группируй связанные проблемы в один пункт\n\n"
        
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
        """Генерировать протокол используя OpenAI GPT"""
        if not self.is_available():
            raise ValueError("OpenAI API не настроен")

        # Извлекаем параметры из kwargs
        speaker_mapping = kwargs.get('speaker_mapping')
        meeting_topic = kwargs.get('meeting_topic')
        meeting_date = kwargs.get('meeting_date')
        meeting_time = kwargs.get('meeting_time')
        participants = kwargs.get('participants')

        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()
        meeting_structure = kwargs.get('meeting_structure')
        user_prompt = _build_user_prompt(
            transcription,
            template_variables,
            diarization_data,
            speaker_mapping,
            meeting_topic,
            meeting_date,
            meeting_time,
            participants,
            meeting_structure
        )
        
        try:
            # Выбор пресета модели, если передан ключ
            selected_model = settings.openai_model
            selected_base_url = settings.openai_base_url or "https://api.openai.com/v1"
            model_key = kwargs.get("openai_model_key")
            if model_key:
                try:
                    preset = next((p for p in settings.openai_models if p.key == model_key), None)
                except Exception:
                    preset = None
                if preset:
                    selected_model = preset.model
                    if getattr(preset, 'base_url', None):
                        selected_base_url = preset.base_url
            
            # Клиент для нужного base_url (по умолчанию используем self.client)
            client = self.client
            if client is None or (selected_base_url and getattr(client, 'base_url', None) != selected_base_url):
                client = openai.OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=selected_base_url,
                    http_client=self.http_client
                )

            # Диагностика запроса (без утечки полной транскрипции)
            base_url = selected_base_url or "https://api.openai.com/v1"
            sys_msg = "Ты - строгий аналитик протоколов встреч..."
            user_len = len(user_prompt)
            transcript_len = len(transcription)
            vars_count = len(template_variables)
            logger.info(
                f"OpenAI запрос: model={selected_model}, base_url={base_url}, "
                f"vars={vars_count}, transcription_chars={transcript_len}, prompt_chars={user_len}"
            )
            _snippet = user_prompt[:400].replace("\n", " ")
            logger.debug(f"OpenAI prompt (фрагмент 400): {_snippet}...")

            # DEBUG логирование запроса
            if settings.llm_debug_log:
                logger.debug("=" * 80)
                logger.debug("[DEBUG] OpenAI REQUEST - generate_protocol")
                logger.debug("=" * 80)
                logger.debug(f"Model: {selected_model}")
                logger.debug(f"Base URL: {selected_base_url}")
                logger.debug(f"Temperature: 0.1")
                logger.debug(f"Extra headers: {extra_headers}")
                logger.debug("-" * 80)
                logger.debug(f"System prompt:\n{system_prompt}")
                logger.debug("-" * 80)
                logger.debug(f"User prompt:\n{user_prompt}")
                logger.debug("=" * 80)

            logger.info(f"Отправляем запрос в OpenAI с моделью {selected_model}")
            
            # Формируем extra_headers для атрибуции
            extra_headers = {}
            if settings.http_referer:
                extra_headers["HTTP-Referer"] = settings.http_referer
            if settings.x_title:
                extra_headers["X-Title"] = settings.x_title
            
            # Выполняем синхронный вызов клиента в отдельном потоке, чтобы не блокировать event loop
            async def _call_openai():
                return await asyncio.to_thread(
                    client.chat.completions.create,
                    model=selected_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    extra_headers=extra_headers
                )
            
            try:
                response = await _call_openai()
            except openai.APIStatusError as e:
                # Проверяем на ошибку 402 - недостаточно кредитов
                if e.status_code == 402:
                    error_message = e.message
                    # Пытаемся извлечь более подробное сообщение из тела ответа
                    if hasattr(e, 'response') and e.response:
                        try:
                            error_body = e.response.json()
                            if 'error' in error_body and 'message' in error_body['error']:
                                error_message = error_body['error']['message']
                        except:
                            pass
                    logger.error(f"Недостаточно кредитов для LLM: {error_message}")
                    raise LLMInsufficientCreditsError(
                        message=error_message,
                        provider="openai",
                        model=selected_model
                    )
                # Другие ошибки API пробрасываем дальше
                raise
            
            logger.info("Получен ответ от OpenAI API")
            
            content = response.choices[0].message.content
            
            # DEBUG логирование ответа
            if settings.llm_debug_log:
                logger.debug("=" * 80)
                logger.debug("[DEBUG] OpenAI RESPONSE - generate_protocol")
                logger.debug("=" * 80)
                if hasattr(response, 'usage'):
                    logger.debug(f"Usage: {response.usage}")
                finish_reason = response.choices[0].finish_reason
                logger.debug(f"Finish reason: {finish_reason}")
                logger.debug("-" * 80)
                logger.debug(f"Content:\n{content}")
                logger.debug("=" * 80)
            logger.info(f"Получен ответ от OpenAI (длина: {len(content) if content else 0}): {content[:200] if content else 'None'}...")
            
            if not content or not content.strip():
                raise ValueError("Получен пустой ответ от OpenAI API")
            
            try:
                # Пытаемся распарсить как JSON напрямую (ожидается при response_format=json_object)
                return json.loads(content)
            except json.JSONDecodeError as e:
                # Мягкий парсер: пытаемся вырезать JSON из текста (как у Anthropic)
                logger.warning(f"Некорректный JSON (прямая загрузка). Пытаемся извлечь из текста: {e}")
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                json_str = content[start_idx:end_idx] if start_idx != -1 and end_idx > start_idx else content
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e2:
                    logger.error(f"Ошибка парсинга JSON ответа от OpenAI (после извлечения): {e2}")
                    logger.error(f"Содержимое ответа: {content}")
                    raise ValueError(f"Некорректный JSON в ответе от OpenAI: {e2}")
            
        except Exception as e:
            logger.error(f"Ошибка при работе с OpenAI API: {e}")
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
        """Генерировать протокол используя Anthropic Claude"""
        if not self.is_available():
            raise ValueError("Anthropic API не настроен")

        # Извлекаем параметры из kwargs
        speaker_mapping = kwargs.get('speaker_mapping')
        meeting_topic = kwargs.get('meeting_topic')
        meeting_date = kwargs.get('meeting_date')
        meeting_time = kwargs.get('meeting_time')
        participants = kwargs.get('participants')

        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()
        meeting_structure = kwargs.get('meeting_structure')
        prompt = _build_user_prompt(
            transcription,
            template_variables,
            diarization_data,
            speaker_mapping,
            meeting_topic,
            meeting_date,
            meeting_time,
            participants,
            meeting_structure
        )
        
        try:
            base_url = "Anthropic SDK"
            user_len = len(prompt)
            transcript_len = len(transcription)
            vars_count = len(template_variables)
            logger.info(
                f"Anthropic запрос: model=claude-3-haiku-20240307, base={base_url}, "
                f"vars={vars_count}, transcription_chars={transcript_len}, prompt_chars={user_len}"
            )
            _a_snippet = prompt[:400].replace("\n", " ")
            logger.debug(f"Anthropic prompt (фрагмент 400): {_a_snippet}...")
            
            # Формируем extra_headers для атрибуции
            extra_headers = {}
            if settings.http_referer:
                extra_headers["HTTP-Referer"] = settings.http_referer
            if settings.x_title:
                extra_headers["X-Title"] = settings.x_title
            
            # Выполняем синхронный вызов клиента Anthropic в отдельном потоке
            async def _call_anthropic():
                return await asyncio.to_thread(
                    self.client.messages.create,
                    model="claude-3-haiku-20240307",
                    max_tokens=2000,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    extra_headers=extra_headers
                )
            response = await _call_anthropic()
            
            content = response.content[0].text
            logger.info(f"Получен ответ от Anthropic (длина: {len(content) if content else 0}): {content[:200] if content else 'None'}...")
            
            if not content or not content.strip():
                raise ValueError("Получен пустой ответ от Anthropic API")
            
            # Пытаемся извлечь JSON из ответа
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            json_str = content[start_idx:end_idx] if start_idx != -1 and end_idx != 0 else content
            
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга JSON ответа от Anthropic: {e}")
                logger.error(f"Содержимое ответа: {content}")
                raise ValueError(f"Некорректный JSON в ответе от Anthropic: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка при работе с Anthropic API: {e}")
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

        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()
        meeting_structure = kwargs.get('meeting_structure')
        prompt = _build_user_prompt(
            transcription,
            template_variables,
            diarization_data,
            speaker_mapping,
            meeting_topic,
            meeting_date,
            meeting_time,
            participants,
            meeting_structure
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
                
                if not content or not content.strip():
                    raise ValueError("Получен пустой ответ от Yandex GPT API")
                
                # Пытаемся извлечь JSON из ответа
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                json_str = content[start_idx:end_idx] if start_idx != -1 and end_idx != 0 else content
                
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка парсинга JSON ответа от Yandex GPT: {e}")
                    logger.error(f"Содержимое ответа: {content}")
                    raise ValueError(f"Некорректный JSON в ответе от Yandex GPT: {e}")
                
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


# ===================================================================
# ДВУХЭТАПНАЯ ГЕНЕРАЦИЯ ПРОТОКОЛА
# ===================================================================

def _build_extraction_prompt(
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    speaker_mapping: Optional[Dict[str, str]] = None,
    meeting_topic: Optional[str] = None,
    meeting_date: Optional[str] = None,
    meeting_time: Optional[str] = None,
    participants: Optional[List[Dict[str, str]]] = None,
    meeting_structure = None,  # MeetingStructure, но избегаем circular import
) -> str:
    """
    Промпт для первого этапа: извлечение и структурирование информации
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
    else:
        transcription_text = f"Транскрипция:\n{transcription}\n\n"
    
    # Добавляем информацию о сопоставлении спикеров
    participants_info = ""
    if speaker_mapping:
        participants_info = "\nУЧАСТНИКИ ВСТРЕЧИ:\n"
        for speaker_id, participant_name in speaker_mapping.items():
            participants_info += f"- {speaker_id} = {participant_name}\n"
        participants_info += "\n⚠️ ИНСТРУКЦИИ ПО УЧАСТНИКАМ:\n"
        participants_info += "- Используй РЕАЛЬНЫЕ ИМЕНА вместо меток спикеров\n"
        participants_info += "- При указании ответственных пиши ТОЛЬКО ИМЯ (без роли в скобках)\n"
        participants_info += "- Формат: 'Задача — Ответственный: Имя Фамилия'\n\n"
        participants_info += "📌 СОПОСТАВЛЕНИЕ ИМЕН:\n"
        participants_info += "Если в транскрипции встречаются сокращенные имена или неполные упоминания —\n"
        participants_info += "сопоставляй их с полными именами из списка участников выше.\n\n"
        participants_info += "Примеры логики (применяй ко ВСЕМ участникам из списка):\n"
        participants_info += "   • Уменьшительные: Света→Светлана, Леша→Алексей и т.д.\n"
        participants_info += "   • По фамилии: Тимченко→Алексей Тимченко и т.д.\n"
        participants_info += "   • Только имя: Алексей→Алексей Тимченко\n\n"
        participants_info += "⚡ Анализируй ВЕСЬ список участников, не только эти примеры!\n"
        participants_info += "⚡ В протоколе используй ПОЛНОЕ ИМЯ из списка.\n\n"
    elif participants:
        # Если нет speaker_mapping, но есть список участников
        participants_info = "\n╔════════════════════════════════════════════════════════╗\n"
        participants_info += "║  🎯 ПОЛНЫЙ СПИСОК УЧАСТНИКОВ (ОБЯЗАТЕЛЕН К ИСПОЛЬЗОВАНИЮ) ║\n"
        participants_info += "╚════════════════════════════════════════════════════════╝\n"
        from src.services.participants_service import participants_service
        participants_info += participants_service.format_participants_for_llm(participants)
        participants_info += "\n\n🚨 СТРОГИЕ ПРАВИЛА:\n"
        participants_info += "1. ТОЛЬКО имена ИЗ СПИСКА ВЫШЕ! Формат: 'Имя Фамилия'\n"
        participants_info += "2. ЗАПРЕЩЕНО: 'Коллега из ОРТ', только имя ('Софья'), только фамилия ('Викулин')\n"
        participants_info += "3. СОПОСТАВЛЕНИЕ сокращений:\n"
        participants_info += "   • 'Света'/'Светочка' → найди 'Светлана' → используй полное имя\n"
        participants_info += "   • 'Леша'/'Алёша' → найди 'Алексей' → используй полное имя\n"
        participants_info += "   • Фамилия ('Викулин') → найди в списке → используй 'Имя Фамилия'\n"
        participants_info += "   • Имя ('Марат') → найди в списке → используй 'Имя Фамилия'\n"
        participants_info += "4. Если НЕ можешь определить конкретного человека - НЕ включай\n\n"
        participants_info += "⚡ ВАЖНО: Используй ТОЧНОЕ написание из списка!\n\n"
    else:
        # Нет ни speaker_mapping, ни participants - автоопределение из транскрипции
        participants_info = "\n⚙️ АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ УЧАСТНИКОВ ИЗ ТРАНСКРИПЦИИ\n"
        participants_info += "═" * 63 + "\n\n"
        participants_info += "Список участников не предоставлен. Определи имена из транскрипции.\n\n"
        participants_info += "📋 ПРАВИЛА ОПРЕДЕЛЕНИЯ:\n\n"
        participants_info += "1️⃣ ИЩИ ЯВНЫЕ УПОМИНАНИЯ:\n"
        participants_info += "   • Представления: 'Меня зовут Иван Петров', 'Я — Мария'\n"
        participants_info += "   • Обращения: 'Света, как думаешь?', 'Петров, расскажи о задаче'\n"
        participants_info += "   • Упоминания: 'Как сказал Иван...', 'Нужно уточнить у Марии'\n\n"
        participants_info += "2️⃣ ФОРМАТ ИМЕН:\n"
        participants_info += "   • Предпочтительно: 'Имя Фамилия' (БЕЗ отчества)\n"
        participants_info += "   • Если известно только имя: 'Иван'\n"
        participants_info += "   • Если известна только фамилия: 'Петров'\n"
        participants_info += "   • Преобразуй уменьшительные: Света→Светлана, Леша→Алексей, Володя→Владимир\n\n"
        participants_info += "3️⃣ СОПОСТАВЛЕНИЕ СО СПИКЕРАМИ:\n"
        participants_info += "   • Сопоставь каждую метку (SPEAKER_1, SPEAKER_2...) с именем если возможно\n"
        participants_info += "   • Если имя определить НЕВОЗМОЖНО - оставь метку спикера как есть\n"
        participants_info += "   • Пример результата: 'Иван Петров\\nСПЕАКЕR_2\\nСветлана Короткова\\nСПЕАКЕR_4'\n\n"
        participants_info += "4️⃣ СТРОГИЕ ЗАПРЕТЫ:\n"
        participants_info += "   ❌ НЕ придумывай имена, которых НЕТ в транскрипции\n"
        participants_info += "   ❌ НЕ используй 'Участник 1', 'Коллега', 'Человек А', 'Неизвестный'\n"
        participants_info += "   ❌ НЕ дублируй: если Света = SPEAKER_1, не добавляй Светлану отдельно\n"
        participants_info += "   ❌ НЕ заменяй SPEAKER_N на описания типа 'Руководитель встречи'\n\n"
        participants_info += "💡 ПОДСКАЗКИ:\n"
        participants_info += "   • Начало встречи - часто там представляются\n"
        participants_info += "   • Обращения по имени - самый надежный признак\n"
        participants_info += "   • Контекст: 'наш тимлид Алексей', 'менеджер Мария'\n"
        participants_info += "   • Уверенности нет? → Оставь SPEAKER_N\n\n"

    # Добавляем информацию о встрече
    meeting_info = ""
    if meeting_topic or meeting_date or meeting_time:
        meeting_info = "\nИНФОРМАЦИЯ О ВСТРЕЧЕ:\n"
        if meeting_topic:
            meeting_info += f"- Тема: {meeting_topic}\n"
        if meeting_date:
            meeting_info += f"- Дата: {meeting_date}\n"
        if meeting_time:
            meeting_info += f"- Время: {meeting_time}\n"
        meeting_info += "\n"
    
    # Добавляем структурный анализ если доступен
    structure_info = ""
    if meeting_structure:
        structure_text = meeting_structure.format_for_llm_prompt()
        if structure_text:
            structure_info = structure_text
    
    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
    
    prompt = f"""ЭТАП 1: ИЗВЛЕЧЕНИЕ ИНФОРМАЦИИ

{transcription_text}{structure_info}{participants_info}{meeting_info}

ЗАДАЧА:
Извлеки из транскрипции информацию для следующих полей:
{variables_str}

ФОРМАТИРОВАНИЕ ОБСУЖДЕНИЯ:
Если группируешь обсуждение по темам/кластерам:
- НЕ пиши слово "Кластер", только название темы с маркером: "• **Название темы**"
- Каждую идею/высказывание/позицию с новой строки
- Формат высказывания: "Имя Автора: текст" (без слова "Идея", без скобок)
- Между тематическими блоками оставляй пустую строку для визуального разделения

Примеры:
✅ ПРАВИЛЬНО:
• **Выбор архитектуры**

Алексей Тимченко: предложил микросервисы

Мария Иванова: поддержала идею

✗ НЕПРАВИЛЬНО:
• Кластер «Выбор архитектуры»: Идея (Алексей Тимченко): предложил...

ТРЕБОВАНИЯ:
1. Используй ТОЛЬКО факты из транскрипции
2. Если информация не найдена явно - пиши "Не указано"
3. Сохраняй хронологический порядок
4. НЕ интерпретируй и НЕ добавляй собственные выводы
5. Для списков используй формат: "- пункт1\\n- пункт2"
6. Для участников: каждое имя с новой строки через \\n, БЕЗ ролей!

КРИТИЧЕСКИ ВАЖНО — форматирование:
- ВСЕ значения должны быть ПРОСТЫМИ СТРОКАМИ (string)
- НЕ используй вложенные объекты {{}} или массивы [] в качестве значений
- Даты: "20 октября 2024", НЕ {{"day": 20, "month": "октябрь"}}
- Участники: "Имя1\\nИмя2\\nИмя3", НЕ [{{"name": "Имя"}}], НЕ "Имя, роль; Имя2"
- Списки: "- элемент1\\n- элемент2", НЕ ["элемент1", "элемент2"]

ПРИМЕР ПРАВИЛЬНОГО JSON:
{{
  "date": "20 октября 2024",
  "participants": "Оксана Иванова\\nГалина Петрова\\nАлексей Смирнов",
  "decisions": "- Решение 1\\n- Решение 2"
}}

ФОРМАТ ВЫВОДА:
Валидный JSON-объект с ключами из списка полей выше.
Каждое значение - строка (UTF-8).

Выведи ТОЛЬКО JSON, без дополнительных комментариев."""

    return prompt


def _build_reflection_prompt(
    extracted_data: Dict[str, Any],
    transcription: str,
    template_variables: Dict[str, str],
    diarization_analysis: Optional[Dict[str, Any]] = None
) -> str:
    """
    Промпт для второго этапа: проверка и улучшение
    """
    extracted_json = json.dumps(extracted_data, ensure_ascii=False, indent=2)
    
    # Добавляем анализ диаризации если есть
    diarization_context = ""
    if diarization_analysis:
        speakers_info = diarization_analysis.get('speakers', {})
        if speakers_info:
            diarization_context = "\n\nАНАЛИЗ УЧАСТНИКОВ:\n"
            for speaker_id, info in speakers_info.items():
                role = info.get('role', 'участник')
                time_percent = info.get('speaking_time_percent', 0)
                diarization_context += f"- {speaker_id} ({role}): {time_percent:.1f}% времени\n"
    
    prompt = f"""ЭТАП 2: ПРОВЕРКА И УЛУЧШЕНИЕ

ИЗВЛЕЧЕННЫЕ ДАННЫЕ (этап 1):
{extracted_json}
{diarization_context}

ИСХОДНАЯ ТРАНСКРИПЦИЯ:
{transcription}


ЗАДАЧА:
Проверь и улучши извлеченные данные, используя исходную транскрипцию:

1. ПРОВЕРКА ПОЛНОТЫ:
   - Все ли важные моменты из транскрипции отражены?
   - Нет ли пропущенных решений, задач или проблем?
   - Достаточно ли детализированы поля?

2. ПРОВЕРКА ТОЧНОСТИ:
   - Все ли факты соответствуют транскрипции?
   - Нет ли домыслов или интерпретаций?
   - Корректны ли имена и термины?

3. ИСПОЛЬЗОВАНИЕ ДИАРИЗАЦИИ:
   - Указаны ли ответственные за задачи из числа спикеров?
   - Отражен ли вклад разных участников?
   - Использована ли информация о ролях спикеров?

4. СТРУКТУРА:
   - Правильно ли отформатированы списки (с дефисами)?
   - Нет ли лишней пунктуации?
   - Логичен ли порядок пунктов?

5. ПРОВЕРКА УЧАСТНИКОВ И ОТВЕТСТВЕННЫХ:
   - Указаны ли реальные имена вместо меток спикеров?
   - В задачах и решениях имена БЕЗ ролей в скобках?
   - Ответственные назначены по смыслу высказываний?
   - Формат: 'Задача — Ответственный: Имя Фамилия' (НЕ 'Имя Фамилия (роль)')

6. СОПОСТАВЛЕНИЕ ИМЕН:
   - Все ли сокращенные/уменьшительные имена заменены на полные из списка участников?
   - Все ли упоминания по фамилии заменены на полное имя из списка?
   - Если в тексте только имя, а в участниках полное - используется ли полное?
   - Проверь ВСЕХ участников из списка, не только очевидные примеры!

ИНСТРУКЦИИ ПО УЛУЧШЕНИЮ:
- Если нашел пропущенную важную информацию - добавь её
- Если нашел неточность - исправь её
- Если можно улучшить формулировку - улучши
- Если можно добавить контекст из диаризации - добавь
- Если видишь роль в скобках у ответственного - УБЕРИ её (оставь только имя)
- НЕ добавляй информацию, которой НЕТ в транскрипции

ФОРМАТ ВЫВОДА:
Валидный JSON-объект с теми же ключами, но улучшенными значениями.
Выведи ТОЛЬКО JSON, без комментариев."""

    return prompt


async def generate_protocol_two_stage(
    manager: 'LLMManager',
    provider_name: str,
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    diarization_analysis: Optional[Dict[str, Any]] = None,
    meeting_structure = None,  # MeetingStructure
    **kwargs
) -> Dict[str, Any]:
    """
    Двухэтапная генерация протокола: извлечение + рефлексия
    
    Args:
        manager: Менеджер LLM
        provider_name: Название провайдера
        transcription: Текст транскрипции
        template_variables: Переменные шаблона
        diarization_data: Данные диаризации
        diarization_analysis: Анализ диаризации
        **kwargs: Дополнительные параметры
        
    Returns:
        Улучшенный протокол
    """
    logger.info("Начало двухэтапной генерации протокола")

    # Извлекаем параметры из kwargs
    speaker_mapping = kwargs.get('speaker_mapping')
    meeting_topic = kwargs.get('meeting_topic')
    meeting_date = kwargs.get('meeting_date')
    meeting_time = kwargs.get('meeting_time')
    participants = kwargs.get('participants')

    # ЭТАП 1: Извлечение информации
    logger.info("Этап 1: Извлечение информации")
    extraction_prompt = _build_extraction_prompt(
        transcription,
        template_variables,
        diarization_data,
        speaker_mapping,
        meeting_topic,
        meeting_date,
        meeting_time,
        participants,
        meeting_structure
    )
    
    # Используем системный промпт (с учетом классификации если включена)
    system_prompt = _build_system_prompt(transcription, diarization_analysis)
    
    # Генерируем первый результат
    if provider_name == "openai":
        provider = manager.providers[provider_name]
        openai_model_key = kwargs.get("openai_model_key")
        
        # Выбор пресета модели
        selected_model = settings.openai_model
        selected_base_url = settings.openai_base_url or "https://api.openai.com/v1"
        
        if openai_model_key:
            try:
                preset = next((p for p in settings.openai_models if p.key == openai_model_key), None)
                if preset:
                    selected_model = preset.model
                    if getattr(preset, 'base_url', None):
                        selected_base_url = preset.base_url
            except Exception:
                pass
        
        # Клиент для нужного base_url
        client = provider.client
        if client is None or (selected_base_url and getattr(client, 'base_url', None) != selected_base_url):
            client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=selected_base_url,
                http_client=provider.http_client
            )
        
        # Формируем extra_headers для атрибуции
        extra_headers = {}
        if settings.http_referer:
            extra_headers["HTTP-Referer"] = settings.http_referer
        if settings.x_title:
            extra_headers["X-Title"] = settings.x_title
        
        # DEBUG логирование запроса этапа 1
        if settings.llm_debug_log:
            logger.debug("=" * 80)
            logger.debug("[DEBUG] OpenAI REQUEST - Two-Stage Extraction (Stage 1)")
            logger.debug("=" * 80)
            logger.debug(f"Model: {selected_model}")
            logger.debug(f"System prompt:\n{system_prompt}")
            logger.debug("-" * 80)
            logger.debug(f"Extraction prompt:\n{extraction_prompt}")
            logger.debug("=" * 80)
        
        # Этап 1: Извлечение
        async def _call_openai_stage1():
            return await asyncio.to_thread(
                client.chat.completions.create,
                model=selected_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": extraction_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                extra_headers=extra_headers
            )
        
        try:
            response1 = await _call_openai_stage1()
        except openai.APIStatusError as e:
            # Проверяем на ошибку 402 - недостаточно кредитов
            if e.status_code == 402:
                error_message = e.message
                # Пытаемся извлечь более подробное сообщение из тела ответа
                if hasattr(e, 'response') and e.response:
                    try:
                        error_body = e.response.json()
                        if 'error' in error_body and 'message' in error_body['error']:
                            error_message = error_body['error']['message']
                    except:
                        pass
                logger.error(f"Недостаточно кредитов для LLM (этап 1): {error_message}")
                raise LLMInsufficientCreditsError(
                    message=error_message,
                    provider="openai",
                    model=selected_model
                )
            # Другие ошибки API пробрасываем дальше
            raise
        
        content1 = response1.choices[0].message.content
        
        # DEBUG логирование ответа этапа 1
        if settings.llm_debug_log:
            logger.debug("=" * 80)
            logger.debug("[DEBUG] OpenAI RESPONSE - Two-Stage Extraction (Stage 1)")
            logger.debug("=" * 80)
            if hasattr(response1, 'usage'):
                logger.debug(f"Usage: {response1.usage}")
            logger.debug(f"Content:\n{content1}")
            logger.debug("=" * 80)
        
        try:
            extracted_data = json.loads(content1)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON на этапе 1: {e}")
            # Пытаемся извлечь JSON из текста
            start_idx = content1.find('{')
            end_idx = content1.rfind('}') + 1
            json_str = content1[start_idx:end_idx] if start_idx != -1 and end_idx > start_idx else content1
            extracted_data = json.loads(json_str)
        
        logger.info(f"Этап 1 завершен, извлечено {len(extracted_data)} полей")
        
        # ЭТАП 2: Рефлексия и улучшение
        logger.info("Этап 2: Рефлексия и улучшение")
        reflection_prompt = _build_reflection_prompt(
            extracted_data, transcription, template_variables, diarization_analysis
        )
        
        # DEBUG логирование запроса этапа 2
        if settings.llm_debug_log:
            logger.debug("=" * 80)
            logger.debug("[DEBUG] OpenAI REQUEST - Two-Stage Reflection (Stage 2)")
            logger.debug("=" * 80)
            logger.debug(f"Reflection prompt:\n{reflection_prompt}")
            logger.debug("=" * 80)
        
        async def _call_openai_stage2():
            return await asyncio.to_thread(
                client.chat.completions.create,
                model=selected_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": reflection_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                extra_headers=extra_headers
            )
        
        try:
            response2 = await _call_openai_stage2()
        except openai.APIStatusError as e:
            # Проверяем на ошибку 402 - недостаточно кредитов
            if e.status_code == 402:
                error_message = e.message
                # Пытаемся извлечь более подробное сообщение из тела ответа
                if hasattr(e, 'response') and e.response:
                    try:
                        error_body = e.response.json()
                        if 'error' in error_body and 'message' in error_body['error']:
                            error_message = error_body['error']['message']
                    except:
                        pass
                logger.error(f"Недостаточно кредитов для LLM (этап 2): {error_message}")
                raise LLMInsufficientCreditsError(
                    message=error_message,
                    provider="openai",
                    model=selected_model
                )
            # Другие ошибки API пробрасываем дальше
            raise
        
        content2 = response2.choices[0].message.content
        finish_reason = response2.choices[0].finish_reason
        
        # DEBUG логирование ответа этапа 2
        if settings.llm_debug_log:
            logger.debug("=" * 80)
            logger.debug("[DEBUG] OpenAI RESPONSE - Two-Stage Reflection (Stage 2)")
            logger.debug("=" * 80)
            if hasattr(response2, 'usage'):
                logger.debug(f"Usage: {response2.usage}")
            logger.debug(f"Finish reason: {response2.choices[0].finish_reason}")
            logger.debug(f"Content:\n{content2}")
            logger.debug("=" * 80)
        
        # Логирование полученного ответа
        logger.info(f"Этап 2: получен ответ длиной {len(content2) if content2 else 0} символов, finish_reason={finish_reason}")
        
        # Проверка на пустой ответ
        if not content2 or not content2.strip():
            logger.warning(f"Этап 2: получен пустой ответ от API. Используем результат этапа 1")
            logger.debug(f"Response details: finish_reason={finish_reason}, model={selected_model}")
            return extracted_data
        
        try:
            improved_data = json.loads(content2)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON на этапе 2: {e}")
            logger.error(f"Content preview (первые 500 символов): {content2[:500]}")
            
            # Попытка извлечь JSON из текста
            start_idx = content2.find('{')
            end_idx = content2.rfind('}') + 1
            
            if start_idx != -1 and end_idx > start_idx:
                json_str = content2[start_idx:end_idx]
                try:
                    improved_data = json.loads(json_str)
                    logger.info("JSON успешно извлечен из текста")
                except json.JSONDecodeError as e2:
                    logger.error(f"Не удалось извлечь JSON: {e2}. Возвращаем результат этапа 1")
                    return extracted_data
            else:
                logger.error("JSON не найден в ответе. Возвращаем результат этапа 1")
                return extracted_data
        
        logger.info(f"Этап 2 завершен успешно")
        return improved_data
    
    else:
        # Для других провайдеров используем стандартный подход
        logger.warning(f"Двухэтапная генерация не поддерживается для {provider_name}, используем стандартный подход")
        return await manager.generate_protocol(
            provider_name, transcription, template_variables, diarization_data, **kwargs
        )


# ===================================================================
# CHAIN-OF-THOUGHT ДЛЯ ДЛИННЫХ ВСТРЕЧ
# ===================================================================

def _build_segment_analysis_prompt(
    segment_text: str,
    segment_id: int,
    total_segments: int,
    template_variables: Dict[str, str],
    speaker_mapping: Optional[Dict[str, str]] = None,
    participants: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Промпт для анализа отдельного сегмента транскрипции
    """
    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
    
    # Добавляем информацию о сопоставлении спикеров с участниками
    participants_info = ""
    if speaker_mapping:
        participants_info = "\n" + "═" * 63 + "\n"
        participants_info += "УЧАСТНИКИ ВСТРЕЧИ (С РОЛЯМИ)\n"
        participants_info += "═" * 63 + "\n\n"
        participants_info += "Сопоставление говорящих с участниками:\n"
        for speaker_id, participant_name in speaker_mapping.items():
            participants_info += f"- {speaker_id} = {participant_name}\n"
        participants_info += "\n"
        participants_info += "⚠️ ИНСТРУКЦИИ ПО РАБОТЕ С УЧАСТНИКАМИ:\n"
        participants_info += "1. Используй РЕАЛЬНЫЕ ИМЕНА вместо меток спикеров (SPEAKER_1 → Имя)\n"
        participants_info += "2. При назначении ответственных учитывай контекст высказываний участников\n"
        participants_info += "3. Формат ответственного: ТОЛЬКО ИМЯ, без роли в скобках\n"
        participants_info += "   ✓ Правильно: 'Ответственный: Иван Петров'\n"
        participants_info += "   ✗ Неправильно: 'Ответственный: Иван Петров (Менеджер)'\n"
        participants_info += "📌 СОПОСТАВЛЕНИЕ ИМЕН:\n"
        participants_info += "В транскрипции могут встречаться сокращенные/разговорные варианты имен.\n"
        participants_info += "АВТОМАТИЧЕСКИ сопоставляй их с полными именами из списка выше:\n\n"
        participants_info += "Примеры логики сопоставления (применяй ко ВСЕМ участникам):\n"
        participants_info += "   • Уменьшительные: Света→Светлана, Леша→Алексей, Саша→Александр и т.д.\n"
        participants_info += "   • По фамилии: Тимченко→Алексей Тимченко, Короткова→Светлана Короткова и т.д.\n"
        participants_info += "   • Только имя: Алексей→Алексей Тимченко (если один такой в списке)\n\n"
        participants_info += "   ⚡ НЕ ограничивайся примерами! Анализируй ВЕСЬ список участников выше.\n"
        participants_info += "   ⚡ В финальном протоколе используй ПОЛНОЕ ИМЯ из списка участников!\n\n"
    elif participants:
        # Если нет speaker_mapping, но есть список участников - показываем его
        participants_info = "\n" + "═" * 63 + "\n"
        participants_info += "🎯 ПОЛНЫЙ СПИСОК УЧАСТНИКОВ ВСТРЕЧИ (ОБЯЗАТЕЛЬНЫЙ К ИСПОЛЬЗОВАНИЮ)\n"
        participants_info += "═" * 63 + "\n\n"
        from src.services.participants_service import participants_service
        participants_info += participants_service.format_participants_for_llm(participants)
        participants_info += "\n\n"
        participants_info += "╔═══════════════════════════════════════════════════════════╗\n"
        participants_info += "║  🚨 КРИТИЧЕСКИ ВАЖНО - СТРОГИЕ ПРАВИЛА ИСПОЛЬЗОВАНИЯ     ║\n"
        participants_info += "╚═══════════════════════════════════════════════════════════╝\n\n"
        participants_info += "1️⃣ ИСПОЛЬЗУЙ ТОЛЬКО ИМЕНА ИЗ СПИСКА ВЫШЕ!\n"
        participants_info += "   ЗАПРЕЩЕНО добавлять участников, которых НЕТ в списке!\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Коллега из ОРТ', 'Коллеги из ERP', 'Команда'\n"
        participants_info += "   ✅ ПРАВИЛЬНО: только конкретные имена из списка\n\n"
        participants_info += "2️⃣ ФОРМАТ ИМЕН: 'Имя Фамилия' (БЕЗ отчества)!\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Софья' (только имя)\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Викулин' (только фамилия)\n"
        participants_info += "   ❌ НЕПРАВИЛЬНО: 'Осипова Софья Юрьевна' (с отчеством)\n"
        participants_info += "   ✅ ПРАВИЛЬНО: 'Софья Осипова', 'Галина Ямкина', 'Владимир Голиков'\n\n"
        participants_info += "3️⃣ СОПОСТАВЛЕНИЕ СОКРАЩЕННЫХ ИМЕН:\n"
        participants_info += "   В транскрипции упоминания могут быть сокращенными.\n"
        participants_info += "   ОБЯЗАТЕЛЬНО найди в списке выше ПОЛНОЕ соответствие:\n\n"
        participants_info += "   📋 ПРАВИЛА СОПОСТАВЛЕНИЯ:\n"
        participants_info += "   • 'Света', 'Светочка' → найди 'Светлана' в списке → используй полное имя\n"
        participants_info += "   • 'Леша', 'Алёша' → найди 'Алексей' в списке → используй полное имя\n"
        participants_info += "   • 'Галя' → найди 'Галина' в списке → используй полное имя\n"
        participants_info += "   • 'Володь', 'Вова' → найди 'Владимир' в списке → используй полное имя\n"
        participants_info += "   • 'Стас' → найди 'Станислав' или 'Святослав' в списке\n"
        participants_info += "   • 'Викулин', 'Тимченко' (фамилия) → найди в списке по фамилии\n"
        participants_info += "   • 'Марат' (имя) → найди в списке по имени → используй полное имя\n\n"
        participants_info += "4️⃣ ПРОВЕРКА ПЕРЕД ДОБАВЛЕНИЕМ В ПРОТОКОЛ:\n"
        participants_info += "   Для КАЖДОГО участника из транскрипции:\n"
        participants_info += "   ✓ Найди соответствие в списке выше\n"
        participants_info += "   ✓ Используй ТОЧНОЕ написание из списка (Имя Фамилия)\n"
        participants_info += "   ✓ Если не можешь определить конкретного человека - НЕ включай в протокол\n\n"
        participants_info += "⚡ ВАЖНО: Проанализируй ВЕСЬ список участников выше!\n"
        participants_info += "⚡ НЕ выдумывай имена! Используй ТОЛЬКО из списка!\n"
        participants_info += "⚡ При малейшем сомнении - сопоставь с полным списком!\n\n"
    else:
        # Нет ни speaker_mapping, ни participants - автоопределение из транскрипции
        participants_info = "\n" + "═" * 63 + "\n"
        participants_info += "⚙️ АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ УЧАСТНИКОВ ИЗ ТРАНСКРИПЦИИ\n"
        participants_info += "═" * 63 + "\n\n"
        participants_info += "Список участников не предоставлен. Определи имена из транскрипции.\n\n"
        participants_info += "📋 ПРАВИЛА ОПРЕДЕЛЕНИЯ:\n\n"
        participants_info += "1️⃣ ИЩИ ЯВНЫЕ УПОМИНАНИЯ:\n"
        participants_info += "   • Представления: 'Меня зовут Иван Петров', 'Я — Мария'\n"
        participants_info += "   • Обращения: 'Света, как думаешь?', 'Петров, расскажи о задаче'\n"
        participants_info += "   • Упоминания: 'Как сказал Иван...', 'Нужно уточнить у Марии'\n\n"
        participants_info += "2️⃣ ФОРМАТ ИМЕН:\n"
        participants_info += "   • Предпочтительно: 'Имя Фамилия' (БЕЗ отчества)\n"
        participants_info += "   • Если известно только имя: 'Иван'\n"
        participants_info += "   • Если известна только фамилия: 'Петров'\n"
        participants_info += "   • Преобразуй уменьшительные: Света→Светлана, Леша→Алексей, Володя→Владимир\n\n"
        participants_info += "3️⃣ СОПОСТАВЛЕНИЕ СО СПИКЕРАМИ:\n"
        participants_info += "   • Сопоставь каждую метку (SPEAKER_1, SPEAKER_2...) с именем если возможно\n"
        participants_info += "   • Если имя определить НЕВОЗМОЖНО - оставь метку спикера как есть\n"
        participants_info += "   • Пример результата: 'Иван Петров\\nСПЕАКЕR_2\\nСветлана Короткова\\nСПЕАКЕR_4'\n\n"
        participants_info += "4️⃣ СТРОГИЕ ЗАПРЕТЫ:\n"
        participants_info += "   ❌ НЕ придумывай имена, которых НЕТ в транскрипции\n"
        participants_info += "   ❌ НЕ используй 'Участник 1', 'Коллега', 'Человек А', 'Неизвестный'\n"
        participants_info += "   ❌ НЕ дублируй: если Света = SPEAKER_1, не добавляй Светлану отдельно\n"
        participants_info += "   ❌ НЕ заменяй SPEAKER_N на описания типа 'Руководитель встречи'\n\n"
        participants_info += "💡 ПОДСКАЗКИ:\n"
        participants_info += "   • Начало встречи - часто там представляются\n"
        participants_info += "   • Обращения по имени - самый надежный признак\n"
        participants_info += "   • Контекст: 'наш тимлид Алексей', 'менеджер Мария'\n"
        participants_info += "   • Уверенности нет? → Оставь SPEAKER_N\n\n"
    
    prompt = f"""CHAIN-OF-THOUGHT: АНАЛИЗ СЕГМЕНТА {segment_id + 1} ИЗ {total_segments}

СЕГМЕНТ ТРАНСКРИПЦИИ:
{segment_text}
{participants_info}
ЗАДАЧА:
Проанализируй этот сегмент встречи и извлеки информацию для следующих категорий:
{variables_str}

ФОРМАТИРОВАНИЕ ОБСУЖДЕНИЯ:
Если группируешь обсуждение по темам/кластерам:
- НЕ пиши слово "Кластер", только название темы с маркером: "• **Название темы**"
- Каждую идею/высказывание/позицию с новой строки
- Формат высказывания: "Имя Автора: текст" (без слова "Идея", без скобок)
- Между тематическими блоками оставляй пустую строку для визуального разделения

Примеры:
✅ ПРАВИЛЬНО:
• **Технические решения**

Алексей Тимченко: предложил использовать Redis для кэширования

✗ НЕПРАВИЛЬНО:
• Кластер «Технические решения»: Идея (Алексей Тимченко): предложил...

ВАЖНО:
- Это сегмент {segment_id + 1} из {total_segments} частей встречи
- Извлекай ТОЛЬКО информацию из ЭТОГО сегмента
- Если в сегменте нет информации для какой-то категории - пиши "Нет в этом сегменте"
- Сохраняй контекст: это часть более длинной встречи
- Для списков используй формат: "- пункт1\\n- пункт2"

ФОРМАТ ВЫВОДА:
JSON-объект с ключами из списка категорий выше.
Каждое значение - строка.

Выведи ТОЛЬКО JSON, без комментариев."""

    return prompt


def _build_synthesis_prompt(
    segment_results: List[Dict[str, Any]],
    transcription: str,
    template_variables: Dict[str, str],
    diarization_analysis: Optional[Dict[str, Any]] = None,
    participants: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Промпт для синтеза финального протокола из результатов сегментов
    """
    # Форматируем результаты сегментов
    segments_summary = ""
    for i, result in enumerate(segment_results):
        segments_summary += f"\n--- СЕГМЕНТ {i + 1} ---\n"
        segments_summary += json.dumps(result, ensure_ascii=False, indent=2)
        segments_summary += "\n"
    
    # Добавляем анализ диаризации если есть
    diarization_context = ""
    if diarization_analysis:
        speakers_info = diarization_analysis.get('speakers', {})
        if speakers_info:
            diarization_context = "\n\nАНАЛИЗ УЧАСТНИКОВ ВСТРЕЧИ:\n"
            for speaker_id, info in speakers_info.items():
                role = info.get('role', 'участник')
                time_percent = info.get('speaking_time_percent', 0)
                diarization_context += f"- {speaker_id} ({role}): {time_percent:.1f}% времени\n"
    
    # Добавляем полный список участников если есть
    participants_context = ""
    if participants:
        participants_context = "\n\nПОЛНЫЙ СПИСОК УЧАСТНИКОВ:\n"
        from src.services.participants_service import participants_service
        participants_context += participants_service.format_participants_for_llm(participants)
        participants_context += "\n"
    
    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
    
    prompt = f"""CHAIN-OF-THOUGHT: СИНТЕЗ ФИНАЛЬНОГО ПРОТОКОЛА

РЕЗУЛЬТАТЫ АНАЛИЗА СЕГМЕНТОВ:
{segments_summary}
{diarization_context}
{participants_context}

ЗАДАЧА:
Объедини информацию из всех сегментов в единый связный протокол для категорий:
{variables_str}

ИНСТРУКЦИИ ПО СИНТЕЗУ:
1. ОБЪЕДИНЕНИЕ: Собери всю информацию из сегментов в единое целое
2. ДЕДУПЛИКАЦИЯ: Удали повторяющуюся информацию между сегментами
3. ХРОНОЛОГИЯ: Сохрани хронологический порядок событий
4. СВЯЗНОСТЬ: Создай связное повествование, а не список фрагментов
5. ПОЛНОТА: Включи всю важную информацию из сегментов
6. КОНТЕКСТ: Используй информацию о спикерах для уточнения ответственных

СПЕЦИАЛЬНЫЕ ПРАВИЛА:
- Если информация из разных сегментов конфликтует - используй более детальную
- Объединяй похожие пункты в списках
- Группируй задачи и решения по смысловым блокам
- Для участников: объедини всех упомянутых, каждое имя с новой строки БЕЗ ролей
- Для задач: укажи ответственных из числа участников если возможно

СОПОСТАВЛЕНИЕ ИМЕН:
- Если в сегментах встречаются сокращенные имена или неполные упоминания участников
- СОПОСТАВЛЯЙ их с полными именами из анализа участников выше
- Примеры логики (применяй ко ВСЕМ участникам из списка):
  • Уменьшительные: Света→Светлана Короткова, Леша→Алексей Тимченко и т.д.
  • По фамилии: Тимченко→Алексей Тимченко и т.д.
  • Только имя: Алексей→Алексей Тимченко
- ⚡ Анализируй ВЕСЬ список участников, не ограничивайся этими примерами!
- В финальном протоколе используй ПОЛНЫЕ ИМЕНА из списка участников

ФОРМАТИРОВАНИЕ ОБСУЖДЕНИЯ:
Если группируешь обсуждение по темам/кластерам:
- НЕ пиши слово "Кластер", только название темы с маркером: "• **Название темы**"
- Каждую идею/высказывание/позицию с новой строки
- Формат высказывания: "Имя Автора: текст" (без слова "Идея", без скобок)
- Между тематическими блоками оставляй пустую строку для визуального разделения

Примеры:
✅ ПРАВИЛЬНО:
• **Создание заказов на обратную логистику**

Алексей Тимченко: сохранить текущую механику создания

Галина Ямкина: добавить валидацию для новых полей

✗ НЕПРАВИЛЬНО:
• Кластер «Создание заказов на обратную логистику»: Идея (Алексей Тимченко): сохранить...

КРИТИЧЕСКИ ВАЖНО — форматирование значений:
- ВСЕ значения в JSON должны быть ПРОСТЫМИ СТРОКАМИ (string)
- НЕ используй вложенные объекты {{}} или массивы [] в качестве значений
- Списки форматируй как многострочный текст: "- пункт1\\n- пункт2\\n- пункт3"
- Даты: простой текст типа "20 октября 2024", НЕ {{"day": 20}}
- Участники: каждое имя с новой строки "Имя1\\nИмя2\\nИмя3", БЕЗ ролей!, НЕ [{{"name": "Имя"}}]
- Время: "14:30" или "с 14:00 до 15:30", НЕ {{"start": "14:00"}}

ПРИМЕР ПРАВИЛЬНОГО ВЫВОДА:
{{
  "date": "20 октября 2024",
  "participants": "Оксана Иванова\\nГалина Петрова\\nАлексей Тимченко",
  "decisions": "- Блокировать редактирование факта для строк с подтвержденными марками\\n- Не стопорить поток из-за ошибок\\n- Оформить требования и CAP-задачи"
}}

ФОРМАТ ВЫВОДА:
JSON-объект с теми же ключами, но с объединенной и улучшенной информацией.
Выведи ТОЛЬКО JSON, без комментариев."""

    return prompt


async def _process_single_segment(
    segment: 'TranscriptionSegment',
    segment_idx: int,
    total_segments: int,
    client: openai.OpenAI,
    selected_model: str,
    system_prompt: str,
    template_variables: Dict[str, str],
    extra_headers: Dict[str, str],
    retry_manager: RetryManager,
    speaker_mapping: Optional[Dict[str, str]] = None,
    participants: Optional[List[Dict[str, str]]] = None
) -> Tuple[int, Dict[str, Any]]:
    """
    Обработать один сегмент транскрипции
    
    Args:
        segment: Сегмент транскрипции
        segment_idx: Индекс сегмента
        total_segments: Общее количество сегментов
        client: OpenAI клиент
        selected_model: Модель для использования
        system_prompt: Системный промпт
        template_variables: Переменные шаблона
        extra_headers: Дополнительные HTTP заголовки
        retry_manager: Менеджер для повторных попыток
        speaker_mapping: Сопоставление спикеров с участниками
        participants: Список участников встречи
        
    Returns:
        Кортеж (индекс_сегмента, результат_обработки)
    """
    logger.info(f"Обработка сегмента {segment_idx + 1}/{total_segments}")
    
    # Используем форматированный текст если есть, иначе обычный
    segment_text = segment.formatted_text if segment.formatted_text else segment.text
    
    # Формируем промпт для сегмента
    segment_prompt = _build_segment_analysis_prompt(
        segment_text=segment_text,
        segment_id=segment_idx,
        total_segments=total_segments,
        template_variables=template_variables,
        speaker_mapping=speaker_mapping,
        participants=participants
    )
    
    # DEBUG логирование запроса сегмента
    if settings.llm_debug_log:
        logger.debug("=" * 80)
        logger.debug(f"[DEBUG] OpenAI REQUEST - Chain-of-Thought Segment {segment_idx + 1}/{total_segments}")
        logger.debug("=" * 80)
        logger.debug(f"Segment prompt:\n{segment_prompt}")
        logger.debug("=" * 80)
    
    # Функция для вызова OpenAI API
    async def _call_openai_api():
        return await asyncio.to_thread(
            client.chat.completions.create,
            model=selected_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": segment_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            extra_headers=extra_headers
        )
    
    # Выполняем запрос с retry логикой
    try:
        response = await retry_manager.execute_with_retry(_call_openai_api)
    except openai.APIStatusError as e:
        # Проверяем на ошибку 402 - недостаточно кредитов
        if e.status_code == 402:
            error_message = e.message
            # Пытаемся извлечь более подробное сообщение из тела ответа
            if hasattr(e, 'response') and e.response:
                try:
                    error_body = e.response.json()
                    if 'error' in error_body and 'message' in error_body['error']:
                        error_message = error_body['error']['message']
                except:
                    pass
            logger.error(f"Недостаточно кредитов для LLM: {error_message}")
            raise LLMInsufficientCreditsError(
                message=error_message,
                provider="openai",
                model=selected_model
            )
        # Другие ошибки API пробрасываем дальше
        raise
    
    content = response.choices[0].message.content
    
    # DEBUG логирование ответа сегмента
    if settings.llm_debug_log:
        logger.debug("=" * 80)
        logger.debug(f"[DEBUG] OpenAI RESPONSE - Chain-of-Thought Segment {segment_idx + 1}/{total_segments}")
        logger.debug("=" * 80)
        if hasattr(response, 'usage'):
            logger.debug(f"Usage: {response.usage}")
        logger.debug(f"Content:\n{content}")
        logger.debug("=" * 80)
    
    # Парсим JSON ответ с обработкой ошибок
    try:
        segment_result = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"Ошибка парсинга JSON для сегмента {segment_idx + 1}: {e}, пытаюсь извлечь JSON из текста")
        start_idx = content.find('{')
        end_idx = content.rfind('}') + 1
        if start_idx != -1 and end_idx > start_idx:
            json_str = content[start_idx:end_idx]
            segment_result = json.loads(json_str)  # Если не удастся - выбросит исключение и сработает retry
        else:
            raise  # Нет JSON в ответе - retry
    
    logger.info(f"Сегмент {segment_idx + 1} обработан успешно")
    
    return (segment_idx, segment_result)


def _merge_segment_results_fallback(
    segment_results: List[Dict[str, Any]], 
    template_variables: Dict[str, str]
) -> Dict[str, Any]:
    """
    Объединяет результаты сегментов в финальный протокол (fallback стратегия).
    Используется когда синтез через LLM не удался.
    
    Args:
        segment_results: Список результатов обработки сегментов
        template_variables: Переменные шаблона
        
    Returns:
        Объединенный протокол
    """
    logger.warning("Используется fallback-стратегия объединения результатов сегментов")
    
    merged = {}
    
    for key in template_variables.keys():
        # Собираем все значения для данного ключа из всех сегментов
        values = []
        for segment in segment_results:
            if key in segment and segment[key]:
                value = segment[key].strip()
                # Пропускаем пустые значения и ошибки
                if value and value != "Не указано" and value != "Нет данных" and "Ошибка" not in value:
                    values.append(value)
        
        # Объединяем значения
        if values:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_values = []
            for v in values:
                # Для списков (начинаются с "- ") разбираем на элементы
                if v.startswith("- ") or v.startswith("• "):
                    items = [line.strip() for line in v.split('\n') if line.strip()]
                    for item in items:
                        if item not in seen:
                            seen.add(item)
                            unique_values.append(item)
                else:
                    if v not in seen:
                        seen.add(v)
                        unique_values.append(v)
            
            merged[key] = "\n".join(unique_values) if unique_values else "Не указано"
        else:
            merged[key] = "Не указано"
    
    return merged


async def generate_protocol_chain_of_thought(
    manager: 'LLMManager',
    provider_name: str,
    transcription: str,
    template_variables: Dict[str, str],
    segments: List['TranscriptionSegment'],
    diarization_data: Optional[Dict[str, Any]] = None,
    diarization_analysis: Optional[Dict[str, Any]] = None,
    meeting_structure = None,  # MeetingStructure
    **kwargs
) -> Dict[str, Any]:
    """
    Chain-of-Thought генерация протокола для длинных встреч
    
    Этапы:
    1. Анализ каждого сегмента отдельно
    2. Синтез финального протокола из результатов сегментов
    
    Args:
        manager: Менеджер LLM
        provider_name: Название провайдера
        transcription: Полный текст транскрипции
        template_variables: Переменные шаблона
        segments: Список сегментов транскрипции
        diarization_data: Данные диаризации
        diarization_analysis: Анализ диаризации
        **kwargs: Дополнительные параметры
        
    Returns:
        Финальный протокол
    """
    logger.info(f"Начало Chain-of-Thought генерации для {len(segments)} сегментов")
    
    # Извлекаем параметры из kwargs
    speaker_mapping = kwargs.get('speaker_mapping')
    participants = kwargs.get('participants')
    
    # Используем системный промпт (с учетом классификации)
    system_prompt = _build_system_prompt(transcription, diarization_analysis)
    
    segment_results = []
    
    # ЭТАП 1: Анализ каждого сегмента
    logger.info("Этап 1: Анализ отдельных сегментов")
    
    if provider_name == "openai":
        provider = manager.providers[provider_name]
        openai_model_key = kwargs.get("openai_model_key")
        
        # Выбор пресета модели
        selected_model = settings.openai_model
        selected_base_url = settings.openai_base_url or "https://api.openai.com/v1"
        
        if openai_model_key:
            try:
                preset = next((p for p in settings.openai_models if p.key == openai_model_key), None)
                if preset:
                    selected_model = preset.model
                    if getattr(preset, 'base_url', None):
                        selected_base_url = preset.base_url
            except Exception:
                pass
        
        # Клиент для нужного base_url
        client = provider.client
        if client is None or (selected_base_url and getattr(client, 'base_url', None) != selected_base_url):
            client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=selected_base_url,
                http_client=provider.http_client
            )
        
        # Формируем extra_headers для атрибуции
        extra_headers = {}
        if settings.http_referer:
            extra_headers["HTTP-Referer"] = settings.http_referer
        if settings.x_title:
            extra_headers["X-Title"] = settings.x_title
        
        # Создаем retry manager для обработки сегментов
        retry_manager = RetryManager(LLM_RETRY_CONFIG)
        
        # Проверяем настройку ограничения параллелизма
        max_parallel = settings.max_parallel_segments
        
        # Обрабатываем каждый сегмент параллельно
        if max_parallel:
            logger.info(
                f"Запуск параллельной обработки {len(segments)} сегментов "
                f"(ограничение: {max_parallel} одновременно)"
            )
            semaphore = asyncio.Semaphore(max_parallel)
            
            async def _process_with_semaphore(segment):
                async with semaphore:
                    return await _process_single_segment(
                        segment=segment,
                        segment_idx=segment.segment_id,
                        total_segments=len(segments),
                        client=client,
                        selected_model=selected_model,
                        system_prompt=system_prompt,
                        template_variables=template_variables,
                        extra_headers=extra_headers,
                        retry_manager=retry_manager,
                        speaker_mapping=speaker_mapping,
                        participants=participants
                    )
            
            tasks = [_process_with_semaphore(segment) for segment in segments]
        else:
            logger.info(f"Запуск параллельной обработки {len(segments)} сегментов (без ограничений)")
            
            tasks = [
                _process_single_segment(
                    segment=segment,
                    segment_idx=segment.segment_id,
                    total_segments=len(segments),
                    client=client,
                    selected_model=selected_model,
                    system_prompt=system_prompt,
                    template_variables=template_variables,
                    extra_headers=extra_headers,
                    retry_manager=retry_manager,
                    speaker_mapping=speaker_mapping,
                    participants=participants
                )
                for segment in segments
            ]
        
        # Параллельная обработка всех сегментов
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обработка результатов
        successful_count = 0
        failed_count = 0
        
        # Сортируем результаты по индексу сегмента для сохранения порядка
        for result in results:
            if isinstance(result, Exception):
                # Если это ошибка недостатка кредитов - немедленно прерываем
                if isinstance(result, LLMInsufficientCreditsError):
                    logger.error(f"Обнаружена ошибка недостатка кредитов, прерываем обработку")
                    raise result
                
                failed_count += 1
                logger.error(f"Ошибка при обработке сегмента: {result}")
                # Добавляем пустой результат
                segment_results.append({
                    key: "Ошибка обработки сегмента" 
                    for key in template_variables.keys()
                })
            else:
                successful_count += 1
                segment_id, data = result
                segment_results.append(data)
        
        logger.info(
            f"Обработка сегментов завершена: успешно {successful_count}/{len(segments)}, "
            f"ошибок {failed_count}/{len(segments)}"
        )
        
        # ЭТАП 2: Синтез финального протокола
        logger.info("Этап 2: Синтез финального протокола из сегментов")
        
        participants = kwargs.get('participants')
        synthesis_prompt = _build_synthesis_prompt(
            segment_results=segment_results,
            transcription=transcription,
            template_variables=template_variables,
            diarization_analysis=diarization_analysis,
            participants=participants
        )
        
        # DEBUG логирование запроса синтеза
        if settings.llm_debug_log:
            logger.debug("=" * 80)
            logger.debug(f"[DEBUG] OpenAI REQUEST - Chain-of-Thought Synthesis ({len(segment_results)} segments)")
            logger.debug("=" * 80)
            logger.debug(f"Synthesis prompt:\n{synthesis_prompt}")
            logger.debug("=" * 80)
        
        async def _call_openai_synthesis():
            return await asyncio.to_thread(
                client.chat.completions.create,
                model=selected_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": synthesis_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                extra_headers=extra_headers
            )
        
        try:
            response_synthesis = await _call_openai_synthesis()
        except openai.APIStatusError as e:
            # Проверяем на ошибку 402 - недостаточно кредитов
            if e.status_code == 402:
                error_message = e.message
                # Пытаемся извлечь более подробное сообщение из тела ответа
                if hasattr(e, 'response') and e.response:
                    try:
                        error_body = e.response.json()
                        if 'error' in error_body and 'message' in error_body['error']:
                            error_message = error_body['error']['message']
                    except:
                        pass
                logger.error(f"Недостаточно кредитов для LLM (синтез): {error_message}")
                raise LLMInsufficientCreditsError(
                    message=error_message,
                    provider="openai",
                    model=selected_model
                )
            # Другие ошибки API пробрасываем дальше
            raise
        
        content_synthesis = response_synthesis.choices[0].message.content
        
        # DEBUG логирование ответа синтеза
        if settings.llm_debug_log:
            logger.debug("=" * 80)
            logger.debug("[DEBUG] OpenAI RESPONSE - Chain-of-Thought Synthesis")
            logger.debug("=" * 80)
            if hasattr(response_synthesis, 'usage'):
                logger.debug(f"Usage: {response_synthesis.usage}")
            logger.debug(f"Content:\n{content_synthesis}")
            logger.debug("=" * 80)
        
        # Проверка на пустой ответ
        if not content_synthesis or not content_synthesis.strip():
            logger.error("Получен пустой ответ от LLM на этапе синтеза")
            logger.warning("Пытаемся использовать fallback-стратегию объединения сегментов")
            return _merge_segment_results_fallback(segment_results, template_variables)
        
        # Проверка на минимальные признаки JSON
        if '{' not in content_synthesis or '}' not in content_synthesis:
            logger.error(f"Ответ не содержит JSON структуры. Длина: {len(content_synthesis)}, начало: {content_synthesis[:200]}")
            logger.warning("Пытаемся использовать fallback-стратегию объединения сегментов")
            return _merge_segment_results_fallback(segment_results, template_variables)
        
        # Первая попытка: прямой парсинг
        try:
            final_protocol = json.loads(content_synthesis)
            logger.info("Chain-of-Thought генерация завершена успешно (прямой парсинг)")
            return final_protocol
        except json.JSONDecodeError as e:
            logger.warning(f"Ошибка прямого парсинга JSON на этапе синтеза: {e}")
            logger.debug(f"Позиция ошибки: line {e.lineno}, column {e.colno}, char {e.pos}")
            
            # Вторая попытка: извлечение JSON из текста
            start_idx = content_synthesis.find('{')
            end_idx = content_synthesis.rfind('}') + 1
            
            if start_idx != -1 and end_idx > start_idx:
                json_str = content_synthesis[start_idx:end_idx]
                logger.debug(f"Пытаемся извлечь JSON из текста: длина {len(json_str)}, начало: {json_str[:100]}")
                
                try:
                    final_protocol = json.loads(json_str)
                    logger.info("Chain-of-Thought генерация завершена успешно (извлечение из текста)")
                    return final_protocol
                except json.JSONDecodeError as e2:
                    logger.error(f"Ошибка парсинга извлеченного JSON: {e2}")
                    logger.error(f"Позиция ошибки: line {e2.lineno}, column {e2.colno}, char {e2.pos}")
                    logger.error(f"Содержимое ответа (первые 1000 символов):\n{content_synthesis[:1000]}")
                    logger.error(f"Содержимое ответа (последние 500 символов):\n{content_synthesis[-500:]}")
            else:
                logger.error(f"Не удалось найти границы JSON в ответе")
                logger.error(f"Полное содержимое ответа:\n{content_synthesis}")
            
            # Fallback: объединяем результаты сегментов напрямую
            logger.warning("Все попытки парсинга JSON не удались, используем fallback-стратегию")
            return _merge_segment_results_fallback(segment_results, template_variables)
    
    else:
        # Для других провайдеров используем стандартный подход
        logger.warning(
            f"Chain-of-Thought не поддерживается для {provider_name}, "
            f"используем стандартный подход"
        )
        # Передаем meeting_structure через kwargs
        if meeting_structure:
            kwargs['meeting_structure'] = meeting_structure
        return await manager.generate_protocol(
            provider_name, transcription, template_variables, diarization_data, **kwargs
        )


# Глобальный экземпляр менеджера LLM
llm_manager = LLMManager()
