"""Действия с готовым протоколом: PDF и перегенерация из истории.

Обработка записи стоит минуты и деньги; готовый протокол хранится в
processing_history вместе с транскрипцией. PDF рендерится из сохранённого
текста, перегенерация другим шаблоном — один LLM-вызов без повторной
транскрипции.
"""

import json
from types import SimpleNamespace
from typing import Dict, Optional

from loguru import logger

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services.result_sender import send_result_to_user
from src.utils.template_sort import template_name_of


def _parse_stored_speaker_mapping(raw: Optional[str]) -> Optional[Dict[str, str]]:
    """Сохранённое сопоставление спикеров (JSON-строка) → dict.

    Битый JSON или неожиданная форма — не повод падать: возвращаем None, и
    перегенерация просто прогонит ЭТАП 1 заново, как для старых записей.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Перегенерация: не удалось разобрать speaker_mapping из истории")
        return None
    if isinstance(parsed, dict) and parsed:
        return {str(k): str(v) for k, v in parsed.items()}
    return None


async def regenerate_protocol(
    bot,
    chat_id: int,
    telegram_user_id: int,
    history_id: int,
    template_id: int,
    user_service,
    template_service,
) -> bool:
    """Сгенерировать протокол заново по другому шаблону из сохранённой истории.

    Возвращает ``True``, только если новый протокол доставлен пользователю.
    """
    from src.database import history_repo

    row = await history_repo.get_result_for_user(history_id, telegram_user_id)
    if not row:
        logger.warning(
            f"Перегенерация: запись {history_id} не найдена или чужая "
            f"(telegram_id={telegram_user_id})"
        )
        return False

    transcription_text = (row.get("transcription_text") or "").strip()
    if not transcription_text:
        logger.warning(f"Перегенерация: у записи {history_id} нет транскрипции")
        return False

    template = await template_service.get_template_by_id(template_id)
    if not template:
        logger.warning(f"Перегенерация: шаблон {template_id} не найден")
        return False

    # Итоги ЭТАПА 1, сохранённые с исходным протоколом. Если оба на месте,
    # генератор пропустит анализ — имена участников совпадут с уже отправленным
    # протоколом. Пусто (старые записи) → полный анализ, как раньше, без ошибок.
    stored_speaker_mapping = _parse_stored_speaker_mapping(row.get("speaker_mapping"))
    stored_meeting_type = row.get("meeting_type") or None

    request = ProcessingRequest(
        file_name=row["file_name"],
        template_id=template_id,
        llm_provider="openai",
        user_id=telegram_user_id,
        language="ru",
        speaker_mapping=stored_speaker_mapping,
    )
    transcription_result = TranscriptionResult(transcription=transcription_text)

    from src.services.processing.llm_generation import (
        LLMGenerationService,
        effective_stage1_outcome,
    )
    from src.services.processing.protocol_formatter import ProtocolFormatter

    llm_gen = LLMGenerationService(user_service, template_service)
    llm_result = await llm_gen.optimized_llm_generation(
        transcription_result, template, request, SimpleNamespace(),
        meeting_type=stored_meeting_type,
    )
    if llm_result is None:
        logger.error(f"Перегенерация {history_id}: LLM вернул пустой результат")
        return False

    warnings: list = []
    protocol_text = ProtocolFormatter().format_protocol(
        template, llm_result, transcription_result, warnings=warnings
    )

    from src.utils.text_processing import humanize_speaker_labels_for_reader

    protocol_text = humanize_speaker_labels_for_reader(protocol_text, warnings)

    template_name = template_name_of(template, default="Шаблон")
    result = ProcessingResult(
        transcription_result=transcription_result,
        protocol_text=protocol_text,
        template_used={"name": template_name},
        llm_provider_used=request.llm_provider,
        llm_model_used=None,
        warnings=warnings,
    )

    # Итоги ЭТАПА 1, реально использованные генератором: сохранённые (если были)
    # либо выведенные заново на старой записи. Оседают в новой записи, чтобы
    # следующая перегенерация (v3) не разошлась с этой (v2) — история «лечится».
    effective_speaker_mapping, effective_meeting_type = effective_stage1_outcome(
        llm_result,
        speaker_mapping_fallback=stored_speaker_mapping,
        meeting_type_fallback=stored_meeting_type,
    )

    # Новая запись истории: кнопки под новым протоколом работают по цепочке, а
    # использованные тип/сопоставление держат следующую перегенерацию консистентной.
    result.history_id = await history_repo.save_processing_result(
        user_id=row["user_id"],
        file_name=row["file_name"],
        template_id=template_id,
        llm_provider=request.llm_provider,
        transcription_text=transcription_text,
        result_text=protocol_text,
        speaker_mapping=effective_speaker_mapping,
        meeting_type=effective_meeting_type,
    )

    return await send_result_to_user(bot, chat_id, telegram_user_id, request, result)
