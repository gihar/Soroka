"""
Processing history and file utilities.

Extracted from ProcessingService to isolate persistence and I/O helpers.
"""

import asyncio
import os

import aiofiles
from loguru import logger

from src.performance.cache_system import performance_cache
from database import db


class ProcessingHistoryService:
    """Handles saving processing history and file-level utilities."""

    def __init__(self, user_service):
        self._user_service = user_service

    async def save_processing_history(self, request, result) -> None:
        """Сохранить информацию об успешной обработке в БД"""
        try:
            user = await self._user_service.get_user_by_telegram_id(request.user_id)
            if not user:
                logger.warning(
                    f"Не удалось сохранить историю обработки: "
                    f"пользователь {request.user_id} не найден"
                )
                return

            transcription_text = ""
            if getattr(result, "transcription_result", None):
                transcription_text = getattr(
                    result.transcription_result,
                    "transcription",
                    "",
                ) or ""

            await db.save_processing_result(
                user_id=user.id,
                file_name=request.file_name,
                template_id=request.template_id,
                llm_provider=result.llm_provider_used,
                transcription_text=transcription_text,
                result_text=result.protocol_text or "",
            )
        except Exception as err:
            logger.error(f"Ошибка при сохранении истории обработки: {err}")

    @staticmethod
    async def calculate_file_hash(file_path: str) -> str:
        """Вычислить хэш файла для кэширования"""
        import hashlib

        hash_obj = hashlib.sha256()

        async with aiofiles.open(file_path, 'rb') as f:
            while chunk := await f.read(8192):
                hash_obj.update(chunk)

        return hash_obj.hexdigest()[:16]

    @staticmethod
    async def cleanup_temp_file(file_path: str):
        """Асинхронная очистка временного файла"""
        try:
            await asyncio.sleep(1)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Удален временный файл: {file_path}")
        except Exception as e:
            logger.warning(f"Не удалось удалить временный файл {file_path}: {e}")

    @staticmethod
    def generate_result_cache_key(request, file_hash: str) -> str:
        """Генерировать ключ кэша для полного результата

        Args:
            request: Запрос на обработку
            file_hash: SHA-256 хеш содержимого файла

        Returns:
            Ключ кэша
        """
        key_data = {
            "file_hash": file_hash,
            "template_id": request.template_id,
            "llm_provider": request.llm_provider,
            "language": request.language,
            "participants_list": request.participants_list,
            "meeting_topic": request.meeting_topic,
            "meeting_date": request.meeting_date,
            "meeting_time": request.meeting_time,
            "speaker_mapping": request.speaker_mapping,
        }
        return performance_cache._generate_key("full_result", key_data)
