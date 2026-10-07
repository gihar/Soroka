"""
История обработки: запись свершившегося результата в БД.

Хеш записи, ключ кеша и судьба временного файла к истории не относятся — они
в «Подготовке записи» (record_preparation).
"""

from loguru import logger

from src.database import history_repo


def history_transcript(transcription_result) -> str:
    """Текст транскрипции для истории — тот, что видела модель.

    Перегенерация («Другой шаблон») работает на сохранённом тексте и подаёт
    модели сохранённое сопоставление спикеров. Сырой текст бэкенда меток
    ``SPEAKER_N`` не несёт — привязать реплики к именам было бы нечем, — поэтому
    храним ``best_transcript``: формат из диаризации, иначе сырой текст.
    getattr: старый закешированный результат мог не иметь свойства.
    """
    if transcription_result is None:
        return ""
    return (
        getattr(transcription_result, "best_transcript", None)
        or getattr(transcription_result, "transcription", "")
        or ""
    )


class ProcessingHistoryService:
    """Запись результатов обработки в историю."""

    def __init__(self, user_service):
        self._user_service = user_service

    async def save_processing_history(self, request, result):
        """Сохранить информацию об успешной обработке в БД.

        Возвращает id записи истории (или None) — по нему работают действия
        с готовым протоколом (PDF, перегенерация).
        """
        try:
            user = await self._user_service.get_user_by_telegram_id(request.user_id)
            if not user:
                logger.warning(
                    f"Не удалось сохранить историю обработки: "
                    f"пользователь {request.user_id} не найден"
                )
                return None

            transcription_text = history_transcript(
                getattr(result, "transcription_result", None)
            )

            return await history_repo.save_processing_result(
                user_id=user.id,
                file_name=request.file_name,
                template_id=request.template_id,
                llm_provider=result.llm_provider_used,
                transcription_text=transcription_text,
                result_text=result.protocol_text or "",
                # getattr: старый закешированный результат мог не иметь этих полей
                speaker_mapping=getattr(result, "speaker_mapping", None),
                meeting_type=getattr(result, "meeting_type", None),
                prompt_version=getattr(result, "prompt_version", None),
            )
        except Exception as err:
            logger.error(f"Ошибка при сохранении истории обработки: {err}")
            return None
