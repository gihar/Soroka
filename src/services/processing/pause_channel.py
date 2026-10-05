"""Канал паузы — всё, что пауза на карточке показывает пользователю.

Модуль паузы (``mapping_pause``) говорит с пользователем только через этот
интерфейс: в проде — Telegram (:class:`TelegramPauseChannel`), в тестах —
фейковый чат. Так пауза тестируется через собственный интерфейс, без патчей
модулей Telegram и без обхода конструктора сервиса обработки.
"""

import asyncio
from typing import Any, Dict, List, Optional, Protocol, Set

from loguru import logger

from src.models.processing import ProcessingRequest, ProcessingResult


class PauseChannel(Protocol):
    """Чат пользователя, в котором стоит пауза."""

    async def silence_tracker(self) -> None:
        """Остановить автообновления трекера прогона и объявить паузу в нём."""

    async def send_previews(
        self,
        *,
        user_id: int,
        speakers: List[str],
        diarization: Any,
        temp_file_path: Optional[str],
        speakers_text: Optional[Dict[str, str]],
    ) -> Set[str]:
        """Прислать фрагменты записи; вернуть спикеров с доставленным фрагментом."""

    async def show_card(self, **card: Any) -> Optional[Any]:
        """Показать карточку сопоставления; None — не удалось."""

    async def say(self, text: str) -> None:
        """Отправить пользователю короткое пояснение простым текстом."""

    async def start_tracker(self) -> Any:
        """Завести трекер прогресса для продолжения после паузы."""

    async def deliver(
        self, request: ProcessingRequest, result: ProcessingResult, tracker: Any
    ) -> bool:
        """Доставить протокол; True — тело протокола дошло."""

    async def report_failure(self, error: Exception) -> None:
        """Сказать пользователю о сбое — текстом по причине, без сырого payload."""


_PAUSE_TRACKER_TEXT = (
    "**Транскрипция завершена**\n\n"
    "Проверьте сопоставление спикеров с участниками в сообщении ниже."
)


class TelegramPauseChannel:
    """Канал паузы поверх Telegram: бот, чат и (опционально) трекер прогона."""

    def __init__(self, bot: Any, chat_id: int, progress_tracker: Any = None):
        self.bot = bot
        self.chat_id = chat_id
        self.progress_tracker = progress_tracker

    @classmethod
    def from_tracker(cls, progress_tracker: Any) -> "TelegramPauseChannel":
        """Канал основного прогона: тот чат, где идёт его трекер."""
        return cls(progress_tracker.bot, progress_tracker.chat_id, progress_tracker)

    async def silence_tracker(self) -> None:
        tracker = self.progress_tracker
        if tracker is None:
            return
        if tracker.update_task:
            task = tracker.update_task
            tracker.update_task = None
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.debug("Автообновления трекера остановлены перед карточкой")

        try:
            from src.utils.telegram_safe import safe_edit_text

            await safe_edit_text(
                tracker.message, _PAUSE_TRACKER_TEXT, parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Не удалось обновить сообщение трекера: {e}")

    async def send_previews(self, **previews: Any) -> Set[str]:
        from src.ux.speaker_audio_preview import send_speaker_audio_previews

        return await send_speaker_audio_previews(
            bot=self.bot, chat_id=self.chat_id, **previews
        )

    async def show_card(self, **card: Any) -> Optional[Any]:
        from src.ux.speaker_mapping_ui import show_mapping_confirmation

        return await show_mapping_confirmation(
            bot=self.bot, chat_id=self.chat_id, **card
        )

    async def say(self, text: str) -> None:
        from src.utils.telegram_safe import safe_send_message

        await safe_send_message(
            bot=self.bot, chat_id=self.chat_id, text=text, parse_mode=None
        )

    async def start_tracker(self) -> Any:
        from src.ux.progress_tracker import ProgressFactory

        return await ProgressFactory.create_file_processing_tracker(
            bot=self.bot, chat_id=self.chat_id
        )

    async def deliver(
        self, request: ProcessingRequest, result: ProcessingResult, tracker: Any
    ) -> bool:
        from src.services.result_sender import send_result_to_user

        return await send_result_to_user(
            bot=self.bot,
            chat_id=self.chat_id,
            user_id=request.user_id,
            request=request,
            result=result,
            progress_tracker=tracker,
        )

    async def report_failure(self, error: Exception) -> None:
        from src.services.error_presentation import resume_failure_message
        from src.utils.telegram_safe import safe_send_message

        await safe_send_message(
            bot=self.bot,
            chat_id=self.chat_id,
            # Сырой str(error) сюда не идёт: у провайдера в payload бывают
            # user_id и параметры запроса, а человеку они ничего не объясняют.
            text=resume_failure_message(str(error)),
        )
