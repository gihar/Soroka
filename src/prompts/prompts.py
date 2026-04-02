"""
Промпты для двухзапросного подхода к генерации протоколов
"""

from typing import Dict, Any, Optional


# Compact field-specific rules for protocol generation.
# Each rule contains ONLY what's unique to this field.
# General rules (JSON format, attribution, list format) are in the system prompt.
FIELD_SPECIFIC_RULES: Dict[str, str] = {
    "participants": """participants — Список участников встречи.
Формат: "Имя Фамилия\\nИмя Фамилия". Извлекай из представлений, обращений, упоминаний. Игнорируй третьих лиц, не присутствующих на встрече. Если имя не определить — оставляй SPEAKER_N.""",

    "date": """date — Дата проведения встречи.
Формат: простой текст, например "20 октября 2024". Извлекай из явных упоминаний или meeting_date. Игнорируй планируемые даты будущих встреч.""",

    "time": """time — Время начала/окончания или продолжительность встречи.
Формат: "14:30" или "с 14:00 до 15:30" или "1,5 часа". Если не упомянуто — используй meeting_time.""",

    "agenda": """agenda — Повестка дня: темы, заявленные ДО начала обсуждения.
Извлекай пункты повестки, озвученные в начале встречи. Спонтанные темы — это для discussion.""",

    "discussion": """discussion — ГЛАВНОЕ ПОЛЕ. Детальное содержание всех обсуждений.
Группируй по темам: "* **Название темы**", затем высказывания с атрибуцией: "Имя Фамилия: текст".
АБСОЛЮТНАЯ ПОЛНОТА: каждая тема, идея, пример, цифра ДОЛЖНЫ быть отражены. Сохраняй хронологию и контекст (тон, уровень согласия). Между тематическими блоками — двойной \\n\\n.""",

    "key_points": """key_points — Ключевые выводы и инсайты встречи (3-7 пунктов).
Извлекай главные выводы, значимые цифры, критические решения. Каждый пункт — самостоятельный и информативный.""",

    "decisions": """decisions — ТОЛЬКО принятые и согласованные решения.
Различай: РЕШЕНО vs ОБСУЖДАЛОСЬ vs ПРЕДЛОЖЕНО. Фиксируй условия ("если получим бюджет...") и инициатора. Идеи без явного решения сюда НЕ включай.""",

    "tasks": """tasks — Задачи и поручения со встречи.
Формат: "- Описание задачи — Ответственный: Имя Фамилия". Ответственного указывай ТОЛЬКО если явно назван или понятен из контекста. Если неизвестен — не указывай.""",

    "tasks_od": """tasks_od — Поручения руководителей (OD).
Формат: НУМЕРОВАННЫЙ список. "N. Название — описание. Отв. Имя Фамилия. Срок — DD.MM.YYYY". Если срока нет — опусти. Если ответственный неизвестен — опусти "Отв.". Связанные поручения — в одном пункте.""",

    "action_items": """action_items — Конкретные действия с ответственными.
Формат: "- Описание задачи — Ответственный: Имя Фамилия". БЕЗ роли в скобках! Если срок упомянут — включи в описание.""",

    "next_steps": """next_steps — Согласованные следующие шаги после встречи.
Конкретные, измеримые действия с относительными сроками ("к концу недели", "к следующей встрече").""",

    "deadlines": """deadlines — Конкретные сроки и дедлайны.
Формат: "- Событие: срок". Сохраняй формат дат как в оригинале. Относительные сроки ("к концу недели") оставляй как есть.""",

    "risks_and_blockers": """risks_and_blockers — Выявленные риски и блокеры.
Формат: "- **Риск/Блокер**: описание и план митигации". Различай риски (потенциальные) и блокеры (текущие).""",

    "speakers_summary": """speakers_summary — Краткая характеристика участников и их вклада.
Формат: "Имя Фамилия (роль): характеристика участия". Фокус на вкладе в эту встречу.""",

    "speaker_contributions": """speaker_contributions — Детальный вклад каждого участника.
Формат: "**Имя Фамилия**:\\n- Идея/предложение\\n- Другая идея". Группируй по участникам, сохраняй хронологию.""",

    "dialogue_analysis": """dialogue_analysis — Анализ динамики обсуждения и взаимодействия.
Фокус на КАК обсуждалось (паттерны, роли, конфликты, консенсус), а не на ЧТО.""",

    "technical_issues": """technical_issues — Технические проблемы, баги, ограничения.
Только технические вопросы. Нетехнические проблемы — в issues.""",

    "architecture_decisions": """architecture_decisions — Архитектурные решения с обоснованием.
Формат: "- Решение. Обоснование: почему". Включай отвергнутые альтернативы.""",

    "technical_tasks": """technical_tasks — Технические задачи (разработка, настройка, оптимизация).
Используй технические термины точно как в транскрипции. Общие задачи — в tasks.""",

    "next_sprint_plans": """next_sprint_plans — Задачи и цели следующего спринта.
Конкретные задачи с приоритетами. Долгосрочные планы без привязки к спринту не включай.""",

    "issues": """issues — Выявленные проблемы, требующие решения.
Фактологически, без эмоций. Технические проблемы — в technical_issues.""",

    "questions": """questions — Открытые вопросы без ответа.
Вопросы, требующие проработки или уточнения. Уже отвеченные не включай.""",

    # --- Educational fields ---

    "learning_objectives": """learning_objectives — Заявленные цели обучения.
Извлекай из явных формулировок ("сегодня изучим...", "цель занятия...").""",

    "key_concepts": """key_concepts — Термины и определения из выступления.
Формат: "- **Термин**: определение". Сохраняй точные формулировки спикера.""",

    "examples_and_cases": """examples_and_cases — Практические примеры и кейсы из выступления.
Указывай контекст (к какой теме относится пример).""",

    "practical_demonstration": """practical_demonstration — Демонстрации спикера (код, инструменты).
Фиксируй что демонстрировалось, ключевые шаги и результаты.""",

    "questions_and_answers": """questions_and_answers — Вопросы аудитории и ответы спикера.
Формат: "**Вопрос** (Имя): текст\\n**Ответ**: текст". Автор неизвестен — "Участник".""",

    "homework": """homework — Задания для самостоятельной работы.
Нумерованный список. Включай сроки и критерии оценки, если озвучены.""",

    "additional_materials": """additional_materials — Рекомендованные ресурсы (книги, ссылки, курсы).
Сохраняй точные URL и названия как в оригинале.""",

    "practical_exercises": """practical_exercises — Упражнения во время занятия.
Нумерованный список с описанием и временем. Указывай формат (индивидуально/в парах/в группах).""",

    "group_work": """group_work — Групповые задания, состав групп и результаты.
Если состав неизвестен — описывай только задания и результаты.""",

    "feedback_session": """feedback_session — Отзывы участников о занятии.
С атрибуцией автора. Формальные "спасибо" без содержания не включай.""",

    "materials": """materials — Раздаточные материалы, использованные на занятии.
Презентации, чек-листы, файлы. Рекомендованные для самостоятельного изучения — в additional_materials.""",

    "participant_contributions": """participant_contributions — Доклады и выступления участников (не спикера).
Формат: "**Имя Фамилия**: тема и ключевые тезисы". Если не было — "Выступления участников не проводились".""",

    "controversial_points": """controversial_points — Спорные моменты и разногласия.
Позиции сторон с атрибуцией, аргументы и итог. Если не было — "Спорных моментов не выявлено".""",

    "professional_secrets": """professional_secrets — Лайфхаки и неочевидные приемы от спикера.
Сохраняй формулировки спикера — они несут экспертную ценность.""",

    "audience_practice": """audience_practice — Попытки участников повторить показанное.
Результаты, типичные ошибки, обратная связь спикера.""",

    "group_formation": """group_formation — Процесс формирования групп.
Принцип, состав, роли. Результаты работы — в group_results.""",

    "group_results": """group_results — Итоги и артефакты групповой работы.
Результаты каждой группы с оценкой спикера/других групп.""",

    "peer_feedback": """peer_feedback — Взаимная обратная связь между участниками.
Формат: "Имя -> Имя: отзыв". Если не было — "Взаимная обратная связь не проводилась".""",

    "individual_reflections": """individual_reflections — Личные выводы участников ("я понял, что...").
Формат: "**Имя Фамилия**: рефлексия". Если не было — "Индивидуальные рефлексии не проводились".""",

    "platform": """platform — Платформа проведения (Zoom, Teams, офлайн).
Простой текст. Если не упомянута — "Не указано".""",

    "poll_results": """poll_results — Результаты опросов и голосований.
Вопрос, варианты, распределение голосов. Если точные цифры неизвестны — качественный результат.""",

    "chat_questions": """chat_questions — Вопросы из текстового чата.
Формат: "**Вопрос** (Имя, чат): текст\\n**Ответ**: текст". Автор неизвестен — "Участник (чат)".""",

    "live_demonstration": """live_demonstration — Живые демонстрации экрана/кода.
Что демонстрировалось, ключевые шаги, результаты. Фиксируй конкретные команды/код.""",

    "downloadable_materials": """downloadable_materials — Файлы и ссылки для скачивания.
Сохраняй URL точно. Zoom-ссылки и организационные ссылки не включай.""",

    "additional_notes": """additional_notes — Прочая важная информация.
Организационные объявления, изменения расписания, контекст. "Ловушка" для важного без другого места.""",
}


def _build_field_specific_rules(template_variables: Dict[str, str]) -> str:
    """
    Генерирует правила для конкретных полей шаблона.
    
    Args:
        template_variables: Словарь с переменными шаблона (ключи - названия полей)
        
    Returns:
        Строка с правилами только для полей, присутствующих в template_variables
    """
    if not template_variables:
        return ""
    
    rules_parts = []
    
    # Порядок полей для логичной группировки
    field_order = [
        "participants", "date", "time",  # Базовые
        "agenda", "discussion", "key_points",  # Содержание
        "decisions", "tasks", "tasks_od", "action_items", "next_steps",  # Решения и действия
        "speakers_summary", "speaker_contributions", "dialogue_analysis",  # Анализ участников
        "technical_issues", "architecture_decisions", "technical_tasks",  # Технические
        "risks_and_blockers", "next_sprint_plans", "deadlines", "issues", "questions",  # Риски и планы
        # Образовательные
        "learning_objectives", "key_concepts", "examples_and_cases",
        "practical_demonstration", "questions_and_answers", "homework",
        "additional_materials", "practical_exercises", "group_work",
        "feedback_session", "materials", "participant_contributions",
        "controversial_points", "professional_secrets", "audience_practice",
        "group_formation", "group_results", "peer_feedback",
        "individual_reflections", "platform", "poll_results",
        "chat_questions", "live_demonstration", "downloadable_materials",
        "additional_notes",
    ]
    
    # Добавляем правила для полей в порядке field_order
    for field_name in field_order:
        if field_name in template_variables:
            rule = FIELD_SPECIFIC_RULES.get(field_name)
            if rule:
                rules_parts.append(rule)
    
    # Добавляем правила для полей, которых нет в field_order (на случай новых полей)
    for field_name in template_variables.keys():
        if field_name not in field_order:
            rule = FIELD_SPECIFIC_RULES.get(field_name)
            if rule:
                rules_parts.append(rule)
    
    if not rules_parts:
        return ""
    
    return "\n\n".join(rules_parts)


def build_analysis_prompt(
    transcription: str,
    participants_list: Optional[str] = None,
    meeting_metadata: Optional[Dict[str, str]] = None,
    # New context parameters
    meeting_agenda: Optional[str] = None,
    project_list: Optional[str] = None
) -> str:
    """
    Создает промпт для первого запроса:
    - Определение типа встречи
    - Сопоставление спикеров с участниками

    Args:
        transcription: Текст транскрипции с метками SPEAKER_N
        participants_list: Список участников
        meeting_metadata: Метаданные встречи (дата, время, тема)
        meeting_agenda: Повестка встречи
        project_list: Список проектов

    Returns:
        Промпт для LLM
    """
    prompt = f"""Проанализируй стенограмму встречи и выполни две задачи:

ЗАДАЧА 1: ОПРЕДЕЛЕНИЕ ТИПА ВСТРЕЧИ
На основе анализа контента стенограммы определи тип встречи:

ТИПЫ ВСТРЕЧ:
- **technical** (техническое): Обсуждение кода, архитектуры, API, баз данных, серверов, тестирования, фреймворков, библиотек, CI/CD, девопса, багов, дебага
- **business** (деловое): Обсуждение бюджета, прибыли, контрактов, сделок, клиентов, продаж, маркетинга, стратегии, финансов, инвестиций, ROI, конкурентов, договоров
- **educational** (образовательное): Обучение, объяснение, изучение, лекции, семинары, тренинги, презентации, передача знаний, менторство
- **brainstorm** (брейншторм): Генерация идей, креативные сессии, предложение вариантов, обсуждение возможностей, инновации, новые подходы
- **status** (статусное): Отчеты о прогрессе, статусные обновления, обсуждение метрик, KPI, результатов достижений, стендапы, ретроспективы
- **general** (общее): Если тип точно не определяется или смешанное содержание

ЛОГИКА ОПРЕДЕЛЕНИЯ:
1. Проанализируй основные темы и ключевые слова в стенограмме
2. Определи доминирующий тип контента
3. Учти характер обсуждения (обучение vs принятие решений vs генерация идей)
4. Выбери ОДИН наиболее подходящий тип

ЗАДАЧА 2: СОПОСТАВЛЕНИЕ СПИКЕРОВ
Изучи список участников и сопоставь метки SPEAKER_1, SPEAKER_2 с реальными именами.

Правила сопоставления:
- Уверенность >= 0.7: включай в speaker_mappings
- Уверенность < 0.7: включай в unmapped_speakers
- Используй формат 'Имя Фамилия' (БЕЗ отчества)
- Учитывай уменьшительные формы: Света→Светлана, Леша→Алексей, Саша→Александр
- Используй контекст высказываний для точного сопоставления

Список участников:
{participants_list or 'Не предоставлен'}"""

    # Add context section if provided
    if meeting_agenda or project_list:
        context_section = "\n\n## ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ВСТРЕЧИ\n\n"

        if meeting_agenda:
            context_section += f"**Повестка встречи:**\n{meeting_agenda}\n\n"

        if project_list:
            context_section += f"**Список проектов:**\n{project_list}\n\n"

        prompt += context_section

    prompt += f"""

СТЕНОГРАММА ВСТРЕЧИ:
{transcription}"""

    return prompt


def build_analysis_system_prompt() -> str:
    """
    Создает системный промпт для первого запроса (определение типа и сопоставление спикеров)
    """
    return """Ты — профессиональный протоколист и эксперт по анализу встреч.

ТВОЯ РОЛЬ:
1. ОПРЕДЕЛИТЬ тип встречи на основе содержания транскрипции
2. ТОЧНО сопоставить метки SPEAKER_N с именами участников

ПРИНЦИПЫ ТОЧНОСТИ:
- Изучай ВЕСЬ текст от первого до последнего слова
- Используй ТОЛЬКО информацию из стенограммы
- Сохраняй точные формулировки, цифры, даты
- Не додумывай и не интерпретируй

ПРАВИЛА ОПРЕДЕЛЕНИЯ ТИПА ВСТРЕЧИ:
- Анализируй основные темы и ключевые слова
- Определи доминирующий характер обсуждения
- Выбери ОДИН наиболее подходящий тип

ПРАВИЛА СОПОСТАВЛЕНИЯ СПИКЕРОВ:
- Ищи явные упоминания имен в контексте высказываний
- Учитывай обращения, представления, контекст речи
- Преобразуй уменьшительные формы в полные
- Требуй уверенность >= 0.7 для надежного сопоставления

ФОРМАТ ВЫВОДА:
Строго валидный JSON с соответствующей схемой. Все значения - строки."""


def build_generation_prompt(
    transcription: str,
    template_variables: Dict[str, str],
    speaker_mapping: Optional[Dict[str, str]] = None,
    meeting_type: str = "general",
    meeting_agenda: Optional[str] = None,
    project_list: Optional[str] = None
) -> str:
    """
    Создает промпт для второго запроса (извлечение данных протокола).
    XML-tagged structure: context -> speakers -> fields -> rules -> transcription.
    """
    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
    type_instructions = _get_type_specific_instructions(meeting_type)

    parts = [f"Извлеки данные из транскрипции для протокола. Тип встречи: {meeting_type}"]

    # Context (before transcription)
    context_parts = []
    if meeting_agenda:
        context_parts.append(f"Повестка встречи:\n{meeting_agenda}")
    if project_list:
        context_parts.append(f"Список проектов:\n{project_list}")
    if context_parts:
        parts.append(f"<context>\n{chr(10).join(context_parts)}\n</context>")

    # Speaker mapping
    if speaker_mapping:
        mapping_str = "\n".join([f"{k} = {v}" for k, v in speaker_mapping.items()])
        parts.append(f"<speakers>\n{mapping_str}\n</speakers>")

    # Fields (rules are now in system prompt for caching)
    parts.append(f"<fields>\n{variables_str}\n</fields>")

    if type_instructions:
        parts.append(type_instructions.strip())

    # Transcription last (largest block)
    parts.append(f"<transcription>\n{transcription}\n</transcription>")

    parts.append("Верни только валидный JSON. Все значения — строки.")

    return "\n\n".join(parts)


def build_generation_system_prompt(
    template_variables: Optional[Dict[str, str]] = None,
) -> str:
    """
    Системный промпт для второго запроса (извлечение данных).

    Field-specific rules are included in the system prompt (stable per template)
    so that OpenAI can cache the prefix and reduce token costs on repeated calls
    with the same template.
    """
    base = (
        "Ты — профессиональный протоколист. Извлекай данные из транскрипции "
        "и заполняй поля протокола.\n\n"

        "ФОРМАТ ВЫВОДА — СТРОГО ВАЛИДНЫЙ JSON:\n"
        "- ВСЕ значения — ПРОСТЫЕ СТРОКИ. НИКАКИХ объектов {} или массивов []\n"
        "- Списки: через \\n с маркером '- '\n"
        "- Если данные отсутствуют — 'Не указано'\n\n"

        "ПРИНЦИПЫ:\n"
        "- Используй ТОЛЬКО факты из транскрипции. НЕ домысливай\n"
        "- Обрабатывай ВСЮ транскрипцию равномерно — начало, середину и конец\n"
        "- Заменяй SPEAKER_N на реальные имена из сопоставления\n"
        "- Указывай КТО что сказал: 'Иван Петров: предложил...'\n\n"

        "КОНТЕКСТ:\n"
        "- Повестка встречи — структурируй discussion по её пунктам\n"
        "- Список проектов — привязывай обсуждения к проектам\n\n"

        "ПРИОРИТЕТ ПОЛЕЙ:\n"
        "- discussion — МАКСИМАЛЬНО подробное\n"
        "- decisions, tasks — точные формулировки с ответственными\n"
        "- participants — полный список"
    )

    if template_variables:
        field_rules = _build_field_specific_rules(template_variables)
        if field_rules:
            base += f"\n\nПРАВИЛА ДЛЯ ПОЛЕЙ:\n{field_rules}"

    return base


def _get_type_specific_instructions(meeting_type: str) -> str:
    """
    Consolidated type-specific instructions (content + formatting merged).
    """
    instructions = {
        'technical': (
            "СПЕЦИФИКА ТЕХНИЧЕСКИХ ВСТРЕЧ:\n"
            "- Сохраняй технические термины на английском как в оригинале\n"
            "- Включай версии, конфигурации, зависимости\n"
            "- Отмечай архитектурные решения с обоснованиями\n"
            "- Фиксируй технические компромиссы, риски, техдолг"
        ),
        'business': (
            "СПЕЦИФИКА ДЕЛОВЫХ ВСТРЕЧ:\n"
            "- Точные финансовые цифры с указанием валюты\n"
            "- Юридически значимые формулировки, условия договоренностей\n"
            "- Коммерческие риски и гарантии\n"
            "- Ответственные лица и их роли"
        ),
        'educational': (
            "СПЕЦИФИКА ОБРАЗОВАТЕЛЬНЫХ ВСТРЕЧ:\n"
            "- Структурируй по темам/разделам\n"
            "- Выделяй термины и определения\n"
            "- Включай примеры и практические задания\n"
            "- Фиксируй вопросы аудитории и ответы"
        ),
        'brainstorm': (
            "СПЕЦИФИКА БРЕЙНШТОРМОВ:\n"
            "- Все идеи без фильтрации, в оригинальной формулировке\n"
            "- Группируй по тематическим блокам с авторами\n"
            "- Отмечай развитие и комбинацию идей\n"
            "- Выделяй выбранные идеи отдельно"
        ),
        'status': (
            "СПЕЦИФИКА ОТЧЕТНЫХ ВСТРЕЧ:\n"
            "- Все метрики и показатели, процент выполнения\n"
            "- Статусы: завершено, в процессе, заблокировано\n"
            "- Критические блокеры и риски\n"
            "- Планы на следующие периоды"
        ),
    }

    return instructions.get(meeting_type, "")


# Keep for backward compatibility — delegates to merged function
def _get_type_specific_formatting_instructions(meeting_type: str) -> str:
    """Deprecated: merged into _get_type_specific_instructions."""
    return ""
