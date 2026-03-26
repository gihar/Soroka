"""
Обработчики callback запросов для обработки файлов и управления задачами.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, ProcessingService
from src.utils.telegram_safe import safe_edit_text
from .helpers import _safe_callback_answer


async def _process_file(callback: CallbackQuery, state: FSMContext, processing_service: ProcessingService):
    """Начать обработку файла"""
    from src.models.processing import ProcessingRequest
    from src.services.task_queue_manager import task_queue_manager
    from src.models.task_queue import TaskPriority
    from src.ux.queue_tracker import QueueTrackerFactory
    import asyncio

    try:
        # Получаем данные из состояния
        data = await state.get_data()

        # ДОБАВЛЕНО: Логирование данных из state для диагностики
        logger.info(f"🔍 Данные из state перед созданием request (callback):")
        participants_list = data.get('participants_list')
        if participants_list:
            logger.info(f"  participants_list: {len(participants_list)} чел.")
            # Показываем первые 3 участника для проверки
            for i, p in enumerate(participants_list[:3], 1):
                logger.info(f"    {i}. {p.get('name')} ({p.get('role', 'без роли')})")
            if len(participants_list) > 3:
                logger.info(f"    ... и еще {len(participants_list) - 3} участников")
        else:
            logger.warning("  participants_list: None (НЕ ПЕРЕДАН!)")
        logger.info(f"  meeting_topic: {data.get('meeting_topic')}")
        logger.info(f"  meeting_date: {data.get('meeting_date')}")
        logger.info(f"  meeting_time: {data.get('meeting_time')}")
        protocol_info = (data.get('protocol_info') or {})
        logger.info(f"  meeting_agenda set: {bool(protocol_info.get('meeting_agenda'))}")
        logger.info(f"  project_list set: {bool(protocol_info.get('project_list'))}")

        # Проверяем наличие LLM (template_id может быть None для умного выбора)
        if not data.get('llm_provider'):
            await safe_edit_text(callback.message,
                "❌ Ошибка: не выбран LLM провайдер. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return

        # Проверяем template_id только если не используется умный выбор
        if (not data.get('use_smart_selection') and
            not data.get('template_id')):
            await safe_edit_text(callback.message,
                "❌ Ошибка: не выбран шаблон. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return

        # Проверяем, что есть либо file_id (для Telegram файлов), либо file_path (для внешних файлов)
        is_external_file = data.get('is_external_file', False)
        if is_external_file:
            if not data.get('file_path') or not data.get('file_name'):
                await safe_edit_text(callback.message,
                    "❌ Ошибка: отсутствуют данные о внешнем файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return
        else:
            if not data.get('file_id') or not data.get('file_name'):
                await safe_edit_text(callback.message,
                    "❌ Ошибка: отсутствуют данные о файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return

        # Создаем запрос на обработку
        request = ProcessingRequest(
            file_id=data.get('file_id') if not is_external_file else None,
            file_path=data.get('file_path') if is_external_file else None,
            file_name=data['file_name'],
            file_url=data.get('file_url'),  # Оригинальный URL для внешних файлов
            template_id=data['template_id'],
            llm_provider=data['llm_provider'],
            user_id=callback.from_user.id,
            language="ru",
            is_external_file=is_external_file,
            # ДОБАВЛЕНО: Передача участников и информации о встрече
            participants_list=data.get('participants_list'),
            meeting_topic=data.get('meeting_topic'),
            meeting_date=data.get('meeting_date'),
            meeting_time=data.get('meeting_time'),
            meeting_agenda=protocol_info.get('meeting_agenda'),
            project_list=protocol_info.get('project_list')
        )

        # ДОБАВЛЕНО: Логирование ProcessingRequest сразу после создания
        logger.info(f"🔍 ProcessingRequest создан, проверка полей:")
        if request.participants_list:
            logger.info(f"  request.participants_list: {len(request.participants_list)} чел.")
        else:
            logger.warning(f"  request.participants_list: None (НЕ ПОПАЛ В REQUEST!)")
        logger.info(f"  request.meeting_topic: {request.meeting_topic}")
        logger.info(f"  request.meeting_date: {request.meeting_date}")
        logger.info(f"  request.meeting_time: {request.meeting_time}")

        # Добавляем задачу в очередь
        queued_task = await task_queue_manager.add_task(
            request=request,
            chat_id=callback.message.chat.id,
            priority=TaskPriority.NORMAL
        )

        # Удаляем старое сообщение с выбором
        try:
            await callback.message.delete()
        except Exception:
            pass

        # Получаем позицию в очереди
        position = await task_queue_manager.get_queue_position(str(queued_task.task_id))
        total_in_queue = await task_queue_manager.get_queue_size()

        # Создаем трекер позиции в очереди
        queue_tracker = await QueueTrackerFactory.create_tracker(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            task_id=str(queued_task.task_id),
            initial_position=position if position is not None else 0,
            total_in_queue=total_in_queue
        )

        # Сохраняем message_id в задаче
        if queue_tracker.message_id:
            queued_task.message_id = queue_tracker.message_id
            from database import db
            await db.update_queue_task_message_id(str(queued_task.task_id), queue_tracker.message_id)

        # Запускаем фоновое обновление позиции в очереди
        from src.handlers.message_handlers import _monitor_queue_position
        asyncio.create_task(_monitor_queue_position(
            queue_tracker, queued_task.task_id, task_queue_manager
        ))

        # Очищаем состояние
        await state.clear()

        logger.info(f"Задача {queued_task.task_id} успешно добавлена в очередь через callback")

    except Exception as e:
        logger.error(f"Ошибка при создании запроса на обработку: {e}")
        await safe_edit_text(callback.message, "❌ Произошла ошибка при подготовке обработки файла.")
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


def setup_processing_callbacks(user_service: UserService, template_service: TemplateService,
                                llm_service: EnhancedLLMService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для обработки файлов"""
    router = Router()

    @router.callback_query(F.data.startswith("set_transcription_mode_"))
    async def set_transcription_mode_callback(callback: CallbackQuery):
        """Обработчик переключения режима транскрипции"""
        try:
            mode = callback.data.replace("set_transcription_mode_", "")

            # Обновляем настройки
            from config import settings
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
                f"✅ **Режим транскрипции изменен на:** {mode_name}\n\n"
                f"Новый режим будет использоваться для всех последующих обработок файлов.",
                parse_mode="Markdown"
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в set_transcription_mode_callback: {e}")
            await callback.answer("❌ Произошла ошибка при изменении режима транскрипции")

    @router.callback_query(F.data.startswith("cancel_task_"))
    async def cancel_task_handler(callback: CallbackQuery, state: FSMContext):
        """Обработчик отмены задачи"""
        await _cancel_task_callback(callback, state)

    return router
