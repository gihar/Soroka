"""Unified prompt builders for all LLM providers."""
from typing import Dict, Any, Optional, List
from loguru import logger
from src.config import settings


def _build_system_prompt(
    transcription: Optional[str] = None,
    diarization_analysis: Optional[Dict[str, Any]] = None,
    llm_meeting_type: Optional[str] = None
) -> str:
    """
    Compact system prompt with primacy zone structure.
    Critical instructions (JSON format, accuracy) go first.
    """
    meeting_type = None

    if llm_meeting_type:
        meeting_type = llm_meeting_type
        logger.info(f"Использую тип встречи определенный LLM: {meeting_type}")
    elif settings.meeting_type_detection and transcription:
        try:
            from src.services.meeting_classifier import meeting_classifier
            meeting_type, _ = meeting_classifier.classify(
                transcription,
                diarization_analysis
            )
            logger.info(f"Использую тип встречи определенный классификатором: {meeting_type}")
        except Exception as e:
            logger.warning(f"Ошибка при классификации встречи: {e}. Используем базовый промпт")

    if meeting_type:
        logger.info(f"Определен тип встречи: {meeting_type} (используем базовый промпт)")

    return (
        "Ты — профессиональный протоколист. Извлекай и структурируй информацию "
        "из стенограмм встреч в четкие, точные протоколы.\n\n"

        # --- PRIMACY ZONE: JSON format (critical for parsing) ---
        "ФОРМАТ ВЫВОДА — СТРОГО ВАЛИДНЫЙ JSON:\n"
        "- ВСЕ значения — ПРОСТЫЕ СТРОКИ (string). НИКАКИХ вложенных объектов {} или массивов []\n"
        "- Списки: многострочный текст через \\n с маркером '- ' (дефис + пробел)\n"
        "- Участники: каждое имя через \\n, формат 'Имя Фамилия' БЕЗ отчества и ролей\n"
        "- Тематические блоки в обсуждении: разделяй двойным \\n\\n\n"
        "- Если данные отсутствуют — пиши 'Не указано'\n\n"
        "Пример:\n"
        "{\n"
        '  "date": "20 октября 2024",\n'
        '  "participants": "Иван Петров\\nМария Сидорова",\n'
        '  "decisions": "- Решение 1\\n- Решение 2"\n'
        "}\n\n"

        # --- ACCURACY PRINCIPLES ---
        "ПРИНЦИПЫ ТОЧНОСТИ:\n"
        "1. Анализируй ВСЮ транскрипцию от первого до последнего слова — каждая тема, "
        "идея, вопрос ДОЛЖНЫ быть отражены\n"
        "2. Используй ТОЛЬКО факты из транскрипции. НЕ домысливай, НЕ интерпретируй\n"
        "3. Все цифры, даты, имена, технологии — записывай ТОЧНО как в оригинале\n"
        "4. Различай 'принято решение' и 'обсуждалась возможность'\n"
        "5. Ответственных и сроки указывай ТОЛЬКО если явно названы\n\n"

        # --- ATTRIBUTION ---
        "АТРИБУЦИЯ:\n"
        "- Указывай КТО что сказал: 'Иван Петров: предложил...'\n"
        "- Заменяй SPEAKER_N на реальные имена из сопоставления\n"
        "- Уменьшительные преобразуй в полные: Света->Светлана, Леша->Алексей\n"
        "- Если имя не определить — оставляй метку SPEAKER_N\n"
        "- НЕ придумывай имена, НЕ используй 'Участник 1', 'Коллега'\n\n"

        # --- DISCUSSION FORMAT ---
        "ФОРМАТИРОВАНИЕ ОБСУЖДЕНИЯ:\n"
        "- Группируй по темам: '* **Название темы**'\n"
        "- Формат: 'Имя Фамилия: текст высказывания'\n"
        "- НЕ используй слова 'Кластер', 'Идея', скобки вокруг имен\n\n"

        # --- WHAT TO IGNORE ---
        "ИГНОРИРУЙ: междометия, запинки, повторы, вводные фразы без смысла, "
        "разговоры не по теме, технические комментарии ('не слышно', 'повторите').\n\n"

        "СТИЛЬ: Официально-деловой язык. Сохраняй профессиональные термины как в оригинале."
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
    meeting_agenda: Optional[str] = None,
    project_list: Optional[str] = None,
) -> str:
    """
    Build user prompt with XML-tagged sections.
    Structure: context -> participants -> transcription -> fields -> rules.
    """
    from src.prompts.prompts import _build_field_specific_rules

    parts = []

    # 1. CONTEXT (meeting info + agenda + projects) — BEFORE transcription
    context_parts = []
    if meeting_topic:
        context_parts.append(f"Тема: {meeting_topic}")
    if meeting_date:
        context_parts.append(f"Дата: {meeting_date}")
    if meeting_time:
        context_parts.append(f"Время: {meeting_time}")
    if meeting_agenda:
        context_parts.append(f"Повестка встречи:\n{meeting_agenda}")
    if project_list:
        context_parts.append(f"Список проектов:\n{project_list}")

    if context_parts:
        parts.append(f"<context>\n{chr(10).join(context_parts)}\n</context>")

    # 2. PARTICIPANTS
    if speaker_mapping:
        mapping_list = "\n".join(f"- {sid} = {name}" for sid, name in speaker_mapping.items())
        parts.append(
            f"<participants>\n"
            f"Сопоставление спикеров:\n{mapping_list}\n\n"
            f"Используй РЕАЛЬНЫЕ ИМЕНА вместо SPEAKER_N. "
            f"Сокращенные имена сопоставляй с полными из списка.\n"
            f"</participants>"
        )
    elif participants:
        from src.services.participants_service import participants_service
        formatted_participants = participants_service.format_participants_for_llm(participants)
        parts.append(
            f"<participants>\n"
            f"{formatted_participants}\n\n"
            f"Используй ТОЛЬКО имена из списка выше. "
            f"Сокращенные формы сопоставляй с полными. "
            f"Если не можешь определить человека — НЕ включай.\n"
            f"</participants>"
        )
    else:
        parts.append(
            "<participants>\n"
            "Список не предоставлен. Определи из транскрипции:\n"
            "- Из представлений, обращений, упоминаний\n"
            "- Формат: 'Имя Фамилия', уменьшительные -> полные\n"
            "- Если имя не определить — оставляй SPEAKER_N\n"
            "</participants>"
        )

    # 3. TRANSCRIPTION
    if diarization_data and diarization_data.get("formatted_transcript"):
        transcription_block = (
            f"<transcription>\n"
            f"{diarization_data['formatted_transcript']}\n"
            f"Говорящих: {diarization_data.get('total_speakers', '?')}\n"
            f"</transcription>"
        )
        if settings.include_raw_transcription_in_prompts:
            transcription_block += (
                f"\n<raw_transcription>\n{transcription}\n</raw_transcription>"
            )
    else:
        transcription_block = (
            f"<transcription>\n{transcription}\n</transcription>"
        )
    parts.append(transcription_block)

    # 4. FIELDS TO EXTRACT
    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
    parts.append(f"<fields>\n{variables_str}\n</fields>")

    # 5. FIELD-SPECIFIC RULES (compact)
    field_rules = _build_field_specific_rules(template_variables)
    if field_rules:
        parts.append(f"<field_rules>\n{field_rules}\n</field_rules>")

    # 6. Final instruction
    parts.append("Верни только валидный JSON без markdown-обертки. Ключи — строго из списка полей.")

    return "\n\n".join(parts)
