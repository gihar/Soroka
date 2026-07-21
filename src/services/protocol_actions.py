"""Действия с готовым протоколом: PDF и перегенерация из истории.

Обработка записи стоит минуты и деньги; готовый протокол хранится в
processing_history вместе с транскрипцией. PDF рендерится из сохранённого
текста, перегенерация другим шаблоном — один LLM-вызов без повторной
транскрипции.
"""

import json
from typing import Dict, Optional

from loguru import logger

from src.models.processing import (
    ProcessingRequest,
    TranscriptionResult,
)
from src.services.result_sender import send_result_to_user


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


class _StoredHistory:
    """История перегенерации: user_id известен из записи-источника.

    Единый хвост (``completion.complete_processing``) пишет историю через
    ``save_processing_history(request, result)``. Для перегенерации владелец уже
    проверен (``get_result_for_user``), поэтому user_id берём прямо из записи —
    без повторного поиска по telegram_id. Итоги ЭТАПА 1 приходят из результата,
    поэтому новая запись «лечит» историю теми же значениями, что и оригинал.
    """

    def __init__(self, source_user_id: int):
        self._source_user_id = source_user_id

    async def save_processing_history(self, request, result) -> Optional[int]:
        from src.database import history_repo

        return await history_repo.save_processing_result(
            user_id=self._source_user_id,
            file_name=request.file_name,
            template_id=request.template_id,
            llm_provider=result.llm_provider_used,
            transcription_text=result.transcription_result.transcription,
            result_text=result.protocol_text or "",
            speaker_mapping=result.speaker_mapping,
            meeting_type=result.meeting_type,
        )


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

    from src.services.processing.completion import (
        CompletionDeps,
        complete_processing,
    )
    from src.services.processing.llm_generation import LLMGenerationService
    from src.services.processing.protocol_formatter import ProtocolFormatter

    deps = CompletionDeps(
        llm_gen=LLMGenerationService(user_service, template_service),
        formatter=ProtocolFormatter(),
        history=_StoredHistory(row["user_id"]),
    )

    async def deliver(result) -> bool:
        return await send_result_to_user(
            bot, chat_id, telegram_user_id, request, result
        )

    # Перегенерация выравнивается по основному пути (ADR-0003): та же сборка
    # результата (полный template_used, резолв имени модели) и страховка замены
    # спикеров. Кеша нет (cache_key=None) — иначе перезаписала бы кеш оригинала
    # того же файла; задачи очереди нет (task_id=None).
    outcome = await complete_processing(
        request=request,
        transcription_result=transcription_result,
        template=template,
        meeting_type=stored_meeting_type,
        deps=deps,
        delivery=deliver,
        cache_key=None,
        task_id=None,
        metrics=None,
    )
    return outcome.delivered
