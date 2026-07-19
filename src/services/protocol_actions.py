"""Действия с готовым протоколом: PDF и перегенерация из истории.

Обработка записи стоит минуты и деньги; готовый протокол хранится в
processing_history вместе с транскрипцией. PDF рендерится из сохранённого
текста, перегенерация другим шаблоном — один LLM-вызов без повторной
транскрипции.
"""

from types import SimpleNamespace

from loguru import logger

from src.models.processing import (
    ProcessingRequest,
    ProcessingResult,
    TranscriptionResult,
)
from src.services.result_sender import send_result_to_user


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

    request = ProcessingRequest(
        file_name=row["file_name"],
        template_id=template_id,
        llm_provider="openai",
        user_id=telegram_user_id,
        language="ru",
    )
    transcription_result = TranscriptionResult(transcription=transcription_text)

    from src.services.processing.llm_generation import LLMGenerationService
    from src.services.processing.protocol_formatter import ProtocolFormatter

    llm_gen = LLMGenerationService(user_service, template_service)
    llm_result = await llm_gen.optimized_llm_generation(
        transcription_result, template, request, SimpleNamespace(), meeting_type=None
    )
    if llm_result is None:
        logger.error(f"Перегенерация {history_id}: LLM вернул пустой результат")
        return False

    warnings: list = []
    protocol_text = ProtocolFormatter().format_protocol(
        template, llm_result, transcription_result, warnings=warnings
    )

    from src.utils.text_processing import humanize_speaker_labels

    protocol_text, unmapped_count = humanize_speaker_labels(protocol_text)
    if unmapped_count:
        warnings.append(
            "ℹ️ Не всех говорящих удалось сопоставить с именами — "
            "в протоколе они обозначены как «Участник N»."
        )

    template_name = getattr(template, "name", None) or "Шаблон"
    result = ProcessingResult(
        transcription_result=transcription_result,
        protocol_text=protocol_text,
        template_used={"name": template_name},
        llm_provider_used=request.llm_provider,
        llm_model_used=None,
        warnings=warnings,
    )

    # Новая запись истории: кнопки под новым протоколом работают по цепочке.
    result.history_id = await history_repo.save_processing_result(
        user_id=row["user_id"],
        file_name=row["file_name"],
        template_id=template_id,
        llm_provider=request.llm_provider,
        transcription_text=transcription_text,
        result_text=protocol_text,
    )

    return await send_result_to_user(bot, chat_id, telegram_user_id, request, result)
