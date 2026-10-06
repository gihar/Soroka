"""
Обработчики callback запросов для обработки файлов и управления задачами.
"""

from typing import Any, Mapping

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from loguru import logger

from src.services import ProcessingService, TemplateService, UserService
from src.services.participants_service import participants_service
from src.services.processing_launch import (
    SMART_SELECTION,
    ExternalRecord,
    LaunchInputError,
    MeetingDetails,
    ProcessingChoice,
    Record,
    RecordLost,
    SpecificTemplate,
    TelegramRecord,
    TemplateNotChosen,
    launch_processing,
)
from src.utils.telegram_safe import safe_edit_text
from src.ux import queue_tracker
from src.ux.html_text import esc
from src.ux.message_builder import RECORD_LOST_FILE, RECORD_LOST_LINK

from .helpers import _safe_callback_answer

# Тексты ошибок запуска. Записи потерянной — общие с приёмом (message_builder).
_TEMPLATE_NOT_CHOSEN = (
    "❌ Шаблон не выбран.\n"
    "Отправьте запись заново и выберите шаблон."
)
_LAUNCH_FAILED = (
    "❌ Не получилось запустить обработку.\n"
    "Отправьте запись заново."
)


def launch_input_from_state(data: Mapping[str, Any]) -> tuple[Record, ProcessingChoice]:
    """Прочитать FSM-словарь диалога как вход «Запуска обработки».

    Единственное место, где ключи состояния превращаются в типизированный
    вход. ``template_id``: 0 — умный выбор, нет ключа — шаблон не выбран.
    Шаблон проверяется раньше записи. Неполный вход — ``LaunchInputError``.
    """
    template_id = data.get('template_id')
    if template_id is None:
        raise TemplateNotChosen()
    template = SMART_SELECTION if template_id == 0 else SpecificTemplate(template_id)

    if data.get('is_external_file'):
        record = ExternalRecord(
            file_path=data.get('file_path'),
            file_name=data.get('file_name'),
            file_url=data.get('file_url'),
        )
    else:
        record = TelegramRecord(file_id=data.get('file_id'), file_name=data.get('file_name'))

    choice = ProcessingChoice(
        template=template,
        participants=data.get('participants_list'),
        meeting=MeetingDetails(
            topic=data.get('meeting_topic'),
            date=data.get('meeting_date'),
            time=data.get('meeting_time'),
            agenda=data.get('meeting_agenda'),
            projects=data.get('project_list'),
        ),
    )
    return record, choice


def _input_error_text(error: LaunchInputError) -> str:
    if isinstance(error, RecordLost):
        return RECORD_LOST_LINK if error.external else RECORD_LOST_FILE
    return _TEMPLATE_NOT_CHOSEN


class _TelegramLaunchChannel:
    """Канал запуска в Telegram: экран выбора — сообщение колбэка."""

    def __init__(self, callback: CallbackQuery):
        self._callback = callback

    async def dismiss_choice(self) -> None:
        try:
            await self._callback.message.delete()
        except Exception as e:
            logger.debug(f"Экран выбора уже не удалить: {e}")

    async def show_queue_position(self, task_id: str, position: int, total: int):
        return await queue_tracker.QueueTrackerFactory.create_tracker(
            bot=self._callback.bot,
            chat_id=self._callback.message.chat.id,
            task_id=task_id,
            initial_position=position,
            total_in_queue=total,
        )


async def start_processing_from_dialog(callback: CallbackQuery, state: FSMContext) -> None:
    """Запустить обработку записи, выбранной в диалоге.

    Хендлеры кладут свой выбор в состояние и зовут эту функцию. Состояние
    очищается при любом исходе: прогон начат либо его нужно начать заново.
    """
    try:
        record, choice = launch_input_from_state(await state.get_data())
        await launch_processing(
            record, choice,
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            channel=_TelegramLaunchChannel(callback),
        )
    except LaunchInputError as e:
        logger.info(f"Запуск обработки отклонён: {e!r}")
        await safe_edit_text(callback.message, _input_error_text(e))
    except Exception as e:
        logger.error(f"Ошибка при создании запроса на обработку: {e}")
        await safe_edit_text(callback.message, _LAUNCH_FAILED)
    finally:
        await state.clear()


async def _cancel_task_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены задачи из очереди"""
    from src.services.task_queue_manager import task_queue_manager
    from src.ux.queue_tracker import QueuePositionTracker

    try:
        # Извлекаем task_id из callback_data
        task_id = callback.data.replace("cancel_task_", "")

        # Отменяем задачу
        success = await task_queue_manager.cancel_task(task_id)

        if success:
            # Обновляем сообщение
            tracker = QueuePositionTracker(callback.bot, callback.message.chat.id, task_id)
            tracker.message_id = callback.message.message_id
            await tracker.show_cancelled()

            logger.info(f"Задача {task_id} отменена пользователем {callback.from_user.id}")
        else:
            # Задача не найдена или уже обрабатывается
            await callback.answer(
                "Задача уже начала обрабатываться и не может быть отменена",
                show_alert=True
            )

    except Exception as e:
        logger.error(f"Ошибка при отмене задачи: {e}")
        await callback.answer("Ошибка при отмене задачи", show_alert=True)


def setup_processing_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для обработки файлов"""
    router = Router()

    @router.callback_query(F.data.startswith("set_transcription_mode_"))
    async def set_transcription_mode_callback(callback: CallbackQuery):
        """Обработчик переключения режима транскрипции"""
        try:
            mode = callback.data.replace("set_transcription_mode_", "")

            # Обновляем настройки
            from src.config import settings
            settings.transcription_mode = mode

            mode_names = {
                "local": "Локальная (Whisper)",
                "cloud": "Облачная (Groq)",
                "hybrid": "Гибридная (Groq + диаризация)",
                "speechmatics": "Speechmatics",
                "deepgram": "Deepgram",
                "leopard": "Leopard (Picovoice)"
            }

            mode_name = mode_names.get(mode, mode)

            await safe_edit_text(callback.message,
                f"✅ <b>Режим транскрипции изменен на:</b> {esc(mode_name)}\n\n"
                f"Новый режим будет использоваться для всех последующих обработок файлов.",
                parse_mode="HTML"
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в set_transcription_mode_callback: {e}")
            await callback.answer("Не удалось изменить режим, попробуйте ещё раз")

    @router.callback_query(F.data == "quick_process_file")
    async def quick_process_file_callback(callback: CallbackQuery, state: FSMContext):
        """Quick process: skip participants/template/LLM selection, use defaults"""
        try:
            data = await state.get_data()
            has_file = (data.get('file_id') or data.get('file_path')) and data.get('file_name')
            if not has_file:
                await callback.answer("❌ Файл не найден. Отправьте файл заново.")
                return

            # Get user preferences
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)

            # Template: user's default or smart selection (0)
            template_id = 0
            if user and getattr(user, 'default_template_id', None):
                template_id = user.default_template_id

            # Сохранённый список участников — часть тех самых «сохранённых
            # настроек», которые обещает кнопка. Раньше он молча обнулялся, и
            # карточка сопоставления становилась длиннее именно у того, кто
            # выбрал быстрый путь.
            participants_list = None
            if user and getattr(user, 'saved_participants', None):
                try:
                    participants_list = participants_service.participants_from_json(
                        user.saved_participants
                    ) or None
                except Exception as e:
                    logger.warning(f"Не удалось прочитать сохранённых участников: {e}")

            # Set state and process
            await state.update_data(
                template_id=template_id,
                participants_list=participants_list
            )

            await safe_edit_text(callback.message,
                "<b>Быстрая обработка</b>\n\n⏳ Начинаю обработку...",
                parse_mode="HTML")
            await _safe_callback_answer(callback)
            await start_processing_from_dialog(callback, state)

        except Exception as e:
            logger.error(f"Ошибка в quick_process_file_callback: {e}")
            await callback.answer("Не удалось запустить обработку, попробуйте ещё раз")

    @router.callback_query(F.data == "configure_file_processing")
    async def configure_file_processing_callback(callback: CallbackQuery, state: FSMContext):
        """Configure: show participants menu (full flow)"""
        try:
            from src.handlers.participants_handlers import show_participants_menu

            # Кнопки «Файл получен» должны перестать работать, но подменять его
            # текст служебным огрызком незачем: тот оставался в чате навсегда и
            # ничего не сообщал (критика v11). Снимаем клавиатуру, текст живёт.
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception as e:
                logger.debug(f"Клавиатуру записи уже не убрать: {e}")
            # callback.message принадлежит боту — передаём реального пользователя явно
            await show_participants_menu(
                callback.message, user_service,
                user_id=callback.from_user.id, state=state,
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в configure_file_processing_callback: {e}")
            await callback.answer("Не удалось открыть настройки, попробуйте ещё раз")

    @router.callback_query(F.data.startswith("cancel_task_"))
    async def cancel_task_handler(callback: CallbackQuery, state: FSMContext):
        """Обработчик отмены задачи"""
        await _cancel_task_callback(callback, state)

    return router
