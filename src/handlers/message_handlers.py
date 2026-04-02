"""
Обработчики сообщений с файлами
"""

import re
import os
import asyncio
from typing import Optional
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import FileService, TemplateService, ProcessingService
from services.url_service import URLService
from src.exceptions.file import FileError, FileSizeError, FileTypeError
from src.exceptions.template import TemplateNotFoundError
from src.utils.telegram_safe import safe_answer, safe_edit_text


def setup_message_handlers(file_service: FileService, template_service: TemplateService,
                          processing_service: ProcessingService) -> Router:
    """Настройка обработчиков сообщений"""
    router = Router()
    
    @router.message(F.content_type.in_({'audio', 'video', 'voice', 'video_note', 'document'}))
    async def media_handler(message: Message, state: FSMContext):
        """Обработчик медиа файлов"""
        try:
            # Определяем тип и получаем файл
            file_obj, file_name, content_type = _extract_file_info(message)
            
            if not file_obj:
                await safe_answer(message, "❌ Не удалось обработать файл. Попробуйте отправить файл еще раз.")
                return
            
            # Валидируем файл
            try:
                file_service.validate_file(file_obj, content_type, file_name)
            except FileSizeError as e:
                from ux.message_builder import MessageBuilder
                error_details = {
                    "type": "size",
                    "actual_size": getattr(file_obj, 'file_size', 0),
                    "max_size": 20
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_answer(message, error_message, parse_mode="Markdown")
                return
            except FileTypeError as e:
                from ux.message_builder import MessageBuilder
                formats = file_service.get_supported_formats()
                error_details = {
                    "type": "format",
                    "extension": file_name.split('.')[-1] if '.' in file_name else "",
                    "supported_formats": formats
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_answer(message, error_message, parse_mode="Markdown")
                return
            except FileError as e:
                from ux.message_builder import MessageBuilder
                error_message = MessageBuilder.error_message("validation", str(e))
                await safe_answer(message, error_message, parse_mode="Markdown")
                return
            
            # Проверяем наличие file_id
            if not file_obj.file_id:
                await safe_answer(
                    message,
                    "❌ Ошибка: не удалось получить идентификатор файла. "
                    "Попробуйте отправить файл еще раз."
                )
                return
            
            # Сохраняем информацию о файле в состоянии
            await state.update_data(
                file_id=file_obj.file_id,
                file_name=file_name
            )
            
            logger.info(f"Файл сохранен в состояние: file_id={file_obj.file_id}, file_name={file_name}")
            
            # Show quick action menu: fast process or configure
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🚀 Быстрая обработка",
                    callback_data="quick_process_file"
                )],
                [InlineKeyboardButton(
                    text="⚙️ Настроить",
                    callback_data="configure_file_processing"
                )]
            ])
            await message.answer(
                "📎 **Файл получен**\n\n"
                "🚀 **Быстрая обработка** — умный шаблон + сохранённые настройки\n"
                "⚙️ **Настроить** — выбрать участников, шаблон, ИИ",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в media_handler: {e}")
            await safe_answer(message, "❌ Произошла ошибка при обработке файла. Попробуйте еще раз.")
    
    # Обрабатываем текст только когда пользователь НЕ в FSM-состоянии
    @router.message(StateFilter(None), F.content_type == 'text')
    async def text_handler(message: Message, state: FSMContext):
        """Обработчик текстовых сообщений (для URL)"""
        try:
            text = message.text.strip()
            
            # Исключаем обработку кнопок меню - они должны обрабатываться в quick_actions
            menu_buttons = [
                "📤 Загрузить файл", "📝 Мои шаблоны", "⚙️ Настройки", 
                "📊 Статистика", "❓ Помощь", "💬 Обратная связь"
            ]
            
            if text in menu_buttons:
                # Пропускаем - пусть обрабатывает другой роутер
                return
            
            # Исключаем команды - они должны обрабатываться в command_handlers или admin_handlers
            if text.startswith('/'):
                # Пропускаем команды - пусть обрабатывает другой роутер
                return
            
            # Проверяем, содержит ли сообщение URL
            if not _contains_url(text):
                await safe_answer(
                    message,
                    "📎 Отправьте файл (аудио или видео) или ссылку на Google Drive/Яндекс.Диск для обработки.\n\n"
                    "Поддерживаемые форматы:\n"
                    "🎵 Аудио: MP3, WAV, M4A, OGG\n"
                    "🎬 Видео: MP4, AVI, MOV, MKV"
                )
                return
            
            # Извлекаем URL из сообщения
            url = _extract_url(text)
            if not url:
                await safe_answer(message, "❌ Не удалось найти корректную ссылку в сообщении.")
                return
            
            # Обрабатываем URL (template_service не нужен на этом этапе)
            await _process_url(message, url, state, template_service)
            
        except Exception as e:
            logger.error(f"Ошибка в text_handler: {e}")
            await safe_answer(message, "❌ Произошла ошибка при обработке сообщения. Попробуйте еще раз.")
    
    return router


async def _show_llm_selection_for_file(message: Message, state: FSMContext, llm_service, processing_service):
    """Показать выбор LLM для обработки файла"""
    try:
        # Получаем данные из состояния
        state_data = await state.get_data()
        file_id = state_data.get('file_id')
        file_path = state_data.get('file_path')
        file_name = state_data.get('file_name')
        template_id = state_data.get('template_id')
        is_external_file = state_data.get('is_external_file', False)
        
        # Проверяем наличие файла (либо file_id для Telegram файлов, либо file_path для внешних файлов)
        if not template_id:
            await message.answer("❌ Ошибка: шаблон не выбран")
            return
            
        if not file_id and not file_path:
            await message.answer("❌ Ошибка: файл не найден")
            return
        
        # Получаем доступные LLM провайдеры
        available_providers = llm_service.get_available_providers()
        
        if not available_providers:
            await message.answer("❌ Нет доступных LLM провайдеров. Проверьте конфигурацию API ключей.")
            return
        
        # Проверяем, есть ли у пользователя сохранённые предпочтения LLM
        from services import UserService
        user_service = UserService()
        user = await user_service.get_user_by_telegram_id(message.from_user.id)
        
        if user and user.preferred_llm is not None:
            preferred_llm = user.preferred_llm
            # Проверяем, что предпочитаемый LLM доступен
            if preferred_llm in available_providers:
                # Сохраняем в состояние и сразу начинаем обработку
                await state.update_data(llm_provider=preferred_llm)
                
                # Формируем отображаемое имя: для OpenAI показываем название модели (без префикса провайдера)
                llm_display = available_providers[preferred_llm]
                if preferred_llm == 'openai':
                    try:
                        from config import settings as app_settings
                        selected_key = getattr(user, 'preferred_openai_model_key', None)
                        preset = None
                        if selected_key:
                            preset = next((p for p in getattr(app_settings, 'openai_models', []) if p.key == selected_key), None)
                        if not preset:
                            models = getattr(app_settings, 'openai_models', [])
                            if models:
                                preset = models[0]
                        if preset and getattr(preset, 'name', None):
                            llm_display = preset.name
                    except Exception:
                        pass

                text = (
                    f"🤖 **Используется LLM: {llm_display}**\n\n"
                    f"⏳ Начинаю обработку файла..."
                )
                await message.answer(text, parse_mode="Markdown")
                
                # Начинаем обработку файла
                await _start_file_processing(message, state, processing_service)
                return
        
        # Если предпочтений нет или предпочитаемый LLM недоступен, показываем выбор
        current_llm = user.preferred_llm if user else 'openai'
        
        # Создаем клавиатуру для выбора LLM
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'✅ ' if provider_key == current_llm else ''}🤖 {provider_name}",
                callback_data=f"select_llm_{provider_key}"
            )]
            for provider_key, provider_name in available_providers.items()
        ])
        
        # Определяем тип файла для отображения
        file_type = "внешний файл" if is_external_file else "файл"
        
        await message.answer(
            f"🤖 **Выберите ИИ для обработки:**\n\n"
            f"Файл: {file_name}\n"
            f"Тип: {file_type}\n\n"
            f"Выберите модель искусственного интеллекта:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе выбора LLM: {e}")
        await message.answer("❌ Произошла ошибка при загрузке доступных ИИ.")


async def _start_file_processing(message: Message, state: FSMContext, processing_service):
    """Начать обработку файла"""
    from src.models.processing import ProcessingRequest
    from src.services.task_queue_manager import task_queue_manager
    from src.models.task_queue import TaskPriority
    from src.ux.queue_tracker import QueueTrackerFactory
    
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        
        # ДОБАВЛЕНО: Логирование данных из state для диагностики
        logger.info(f"🔍 Данные из state перед созданием request:")
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
            await message.answer(
                "❌ Ошибка: не выбран LLM провайдер. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return
        
        # Проверяем template_id только если не используется умный выбор
        if (not data.get('use_smart_selection') and 
            not data.get('template_id')):
            await message.answer(
                "❌ Ошибка: не выбран шаблон. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return
        
        # Проверяем, что есть либо file_id (для Telegram файлов), либо file_path (для внешних файлов)
        is_external_file = data.get('is_external_file', False)
        if is_external_file:
            if not data.get('file_path') or not data.get('file_name'):
                await message.answer(
                    "❌ Ошибка: отсутствуют данные о внешнем файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return
        else:
            if not data.get('file_id') or not data.get('file_name'):
                await message.answer(
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
            user_id=message.from_user.id,
            language="ru",
            is_external_file=is_external_file,
            participants_list=data.get('participants_list'),  # список участников
            meeting_topic=data.get('meeting_topic'),  # тема встречи
            meeting_date=data.get('meeting_date'),  # дата встречи
            meeting_time=data.get('meeting_time'),  # время встречи
            meeting_agenda=protocol_info.get('meeting_agenda'),  # повестка встречи
            project_list=protocol_info.get('project_list')  # список проектов
        )
        
        # ДОБАВЛЕНО: Логирование ProcessingRequest сразу после создания
        logger.info(f"🔍 ProcessingRequest создан, проверка полей (message):")
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
            chat_id=message.chat.id,
            priority=TaskPriority.NORMAL
        )
        
        # Получаем позицию в очереди
        position = await task_queue_manager.get_queue_position(str(queued_task.task_id))
        total_in_queue = await task_queue_manager.get_queue_size()
        
        # Создаем трекер позиции в очереди
        queue_tracker = await QueueTrackerFactory.create_tracker(
            bot=message.bot,
            chat_id=message.chat.id,
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
        asyncio.create_task(_monitor_queue_position(
            queue_tracker, queued_task.task_id, task_queue_manager
        ))
        
        # Очищаем состояние
        await state.clear()
        
        logger.info(f"Задача {queued_task.task_id} успешно добавлена в очередь")
            
    except Exception as e:
        logger.error(f"Ошибка при создании запроса на обработку: {e}")
        await message.answer("❌ Произошла ошибка при подготовке обработки файла.")
        await state.clear()


async def _monitor_queue_position(queue_tracker, task_id, queue_manager):
    """Мониторинг изменения позиции задачи в очереди"""
    from config import settings
    
    try:
        while queue_tracker.is_active:
            # Получаем текущую позицию
            position = await queue_manager.get_queue_position(str(task_id))
            
            # Если задачи больше нет в очереди (началась обработка или завершена)
            if position is None:
                # Удаляем сообщение про очередь
                await queue_tracker.delete_message()
                break
            
            # Получаем общий размер очереди
            total = await queue_manager.get_queue_size()
            
            # Обновляем отображение только если позиция изменилась
            await queue_tracker.update_position(position, total)
            
            # Ждем перед следующей проверкой
            await asyncio.sleep(settings.queue_update_interval)
    
    except asyncio.CancelledError:
        logger.debug(f"Мониторинг позиции задачи {task_id} отменен")
    except Exception as e:
        logger.error(f"Ошибка в мониторинге позиции задачи {task_id}: {e}")


def _fix_markdown_tags(text: str) -> str:
    """Исправить незакрытые Markdown-теги в тексте"""
    # Подсчитываем количество открытых/закрытых тегов
    bold_count = text.count('**')
    italic_count = text.count('_')
    code_count = text.count('`')
    
    # Закрываем незакрытые теги
    if bold_count % 2 != 0:
        text = text + '**'
    if italic_count % 2 != 0:
        text = text + '_'
    if code_count % 2 != 0:
        text = text + '`'
    
    return text


async def _send_long_protocol(message: Message, protocol_text: str):
    """Отправить длинный протокол частями"""
    try:
        # Максимальная длина сообщения в Telegram (с запасом)
        MAX_LENGTH = 4000
        
        logger.info(f"Начинаем разбивку протокола длиной {len(protocol_text)} символов на части")
        
        # Разбиваем протокол на части
        parts = []
        current_part = ""
        
        # Разбиваем по строкам, чтобы не разрывать слова
        lines = protocol_text.split('\n')
        logger.info(f"Разбиваем на {len(lines)} строк")
        
        for line_num, line in enumerate(lines):
            # Проверяем, поместится ли строка в текущую часть
            if len(current_part) + len(line) + 1 <= MAX_LENGTH:
                current_part += line + '\n'
            else:
                # Если текущая часть не пустая, добавляем её в список частей
                if current_part.strip():
                    parts.append(current_part.strip())
                    logger.debug(f"Добавлена часть {len(parts)} длиной {len(current_part.strip())} символов")
                # Начинаем новую часть
                current_part = line + '\n'
        
        # Добавляем последнюю часть, если она не пустая
        if current_part.strip():
            parts.append(current_part.strip())
            logger.debug(f"Добавлена последняя часть {len(parts)} длиной {len(current_part.strip())} символов")
        
        logger.info(f"Протокол разбит на {len(parts)} частей")
        
        # Отправляем части
        for i, part in enumerate(parts):
            try:
                if i == 0:
                    # Первая часть
                    part_text = f"📄 **Протокол встречи:**\n\n{part}"
                else:
                    # Остальные части с номером
                    part_text = f"📄 **Протокол встречи (часть {i+1}):**\n\n{part}"
                
                # Исправляем незакрытые Markdown-теги
                part_text = _fix_markdown_tags(part_text)
                
                logger.debug(f"Отправляем часть {i+1}/{len(parts)} длиной {len(part_text)} символов")
                await message.answer(part_text, parse_mode="Markdown")
                
                # Небольшая задержка между сообщениями
                import asyncio
                await asyncio.sleep(0.5)
                
            except Exception as part_error:
                logger.error(f"Ошибка при отправке части {i+1}: {part_error}")
                # Пытаемся отправить часть без Markdown
                try:
                    await message.answer(f"📄 Протокол (часть {i+1}):\n\n{part}")
                except Exception as fallback_error:
                    logger.error(f"Не удалось отправить часть {i+1} даже без Markdown: {fallback_error}")
                    await message.answer(f"❌ Ошибка при отправке части {i+1} протокола")
            
    except Exception as e:
        logger.error(f"Ошибка при отправке длинного протокола: {e}")
        # Если не удалось разбить, отправляем как есть (может быть обрезано)
        try:
            truncated_text = protocol_text[:MAX_LENGTH] + "...\n\n(Протокол был обрезан из-за ограничений Telegram)"
            logger.info(f"Отправляем обрезанный протокол длиной {len(truncated_text)} символов")
            await message.answer(truncated_text, parse_mode="Markdown")
        except Exception as fallback_error:
            logger.error(f"Не удалось отправить даже обрезанный протокол: {fallback_error}")
            await message.answer("❌ Ошибка при отправке протокола. Попробуйте еще раз.")


def _extract_file_info(message: Message) -> tuple:
    """Извлечь информацию о файле из сообщения"""
    file_obj = None
    file_name = None
    content_type = None
    
    if message.audio:
        file_obj = message.audio
        # Сохраняем оригинальное расширение файла или используем mime_type
        original_name = getattr(message.audio, 'file_name', None)
        if original_name:
            # Если есть оригинальное имя, сохраняем расширение
            import os
            _, ext = os.path.splitext(original_name)
            file_name = f"audio_{message.message_id}{ext or '.mp3'}"
        else:
            # Определяем расширение по mime_type
            mime_type = getattr(message.audio, 'mime_type', '')
            if 'mp4' in mime_type or 'm4a' in mime_type:
                ext = '.m4a'
            elif 'wav' in mime_type:
                ext = '.wav'
            elif 'ogg' in mime_type:
                ext = '.ogg'
            else:
                ext = '.mp3'  # По умолчанию
            file_name = f"audio_{message.message_id}{ext}"
        content_type = "audio"
    elif message.voice:
        file_obj = message.voice
        file_name = f"voice_{message.message_id}.ogg"
        content_type = "voice"
    elif message.video:
        file_obj = message.video
        # Аналогично для видео
        original_name = getattr(message.video, 'file_name', None)
        if original_name:
            import os
            _, ext = os.path.splitext(original_name)
            file_name = f"video_{message.message_id}{ext or '.mp4'}"
        else:
            file_name = f"video_{message.message_id}.mp4"
        content_type = "video"
    elif message.video_note:
        file_obj = message.video_note
        file_name = f"video_note_{message.message_id}.mp4"
        content_type = "video_note"
    elif message.document:
        file_obj = message.document
        file_name = message.document.file_name or f"document_{message.message_id}"
        content_type = "document"
    
    return file_obj, file_name, content_type


async def _show_template_selection_step2(message: Message, template_service: TemplateService, state: FSMContext = None, participants_count: Optional[int] = None, real_user_id: Optional[int] = None):
    """Показать выбор шаблонов (шаг 2)"""
    try:
        # Детальное логирование для отладки
        logger.info(f"[DEBUG] _show_template_selection_step2 вызван: message.from_user.id={message.from_user.id}, message.chat.id={message.chat.id}")

        # ИСПРАВЛЕНИЕ: Используем правильный ID пользователя
        # 1. Если передан real_user_id (из callback), используем его
        # 2. Иначе используем message.chat.id вместо message.from_user.id
        # Когда бот редактирует сообщения, message.from_user становится ID бота, а message.chat.id остается ID пользователя
        if real_user_id:
            user_id = real_user_id
            logger.info(f"[DEBUG] Используем переданный real_user_id={user_id}")
        else:
            user_id = message.chat.id
            logger.info(f"[DEBUG] Используем user_id={user_id} (message.chat.id) вместо message.from_user.id={message.from_user.id}")

        # Проверяем, есть ли у пользователя шаблон по умолчанию
        from services import UserService
        user_service = UserService()
        default_template_id = await user_service.get_user_default_template_id(user_id)
        logger.info(f"[DEBUG] get_user_default_template_id вернул: {default_template_id} для пользователя {user_id}")

        if default_template_id is None:
            logger.debug(f"У пользователя {user_id} нет сохранённого шаблона по умолчанию")
        else:
            logger.info(f"[DEBUG] Найден шаблон по умолчанию: {default_template_id} для пользователя {user_id}")
        
        # Создаем клавиатуру с новым меню выбора
        keyboard_buttons = []
        
        # Кнопка 1: Умный выбор (всегда показывать первой)
        keyboard_buttons.append([InlineKeyboardButton(
            text="🤖 Протокол: Умный выбор шаблона",
            callback_data="quick_smart_select"
        )])
        
        # Кнопка 2: Сохранённый шаблон (если есть)
        if default_template_id is not None:
            default_id = default_template_id
            button_text = None
            try:
                if default_id == 0:
                    button_text = "🤖 Протокол: Умный выбор (по умолчанию)"
                else:
                    try:
                        default_template = await template_service.get_template_by_id(default_id)
                        button_text = f"📋 По шаблону: {default_template.name}"
                    except TemplateNotFoundError:
                        button_text = f"📋 По шаблону (ID {default_id})"
                
                if button_text:
                    keyboard_buttons.append([InlineKeyboardButton(
                        text=button_text,
                        callback_data="use_saved_default"
                    )])
            except Exception as e:
                logger.warning(f"Не удалось получить шаблон по умолчанию: {e}")
        
        # Кнопка 4: Выбрать шаблон (для разового использования)
        keyboard_buttons.append([InlineKeyboardButton(
            text="📋 Выбрать шаблон",
            callback_data="select_template_once"
        )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Формируем текст сообщения
        message_text = ""
        
        # Если передано количество участников, добавляем подтверждение
        if participants_count is not None:
            message_text = f"✅ Список участников сохранен ({participants_count} чел.)\n\n"
        
        message_text += (
            "📝 **Выберите способ создания протокола:**\n\n"
            "🤖 **Умный выбор** - ИИ автоматически подберёт подходящий шаблон\n"
            "📋 **По шаблону** - использовать сохранённый шаблон\n"
            "📋 **Выбрать шаблон** - выбрать шаблон для текущей обработки"
        )
        
        await message.answer(
            message_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе шаблонов: {e}")
        await message.answer("❌ Произошла ошибка при загрузке шаблонов.")


def _contains_url(text: str) -> bool:
    """Проверить, содержит ли текст URL"""
    url_pattern = r'https?://[^\s]+'
    return bool(re.search(url_pattern, text))


def _extract_url(text: str) -> str:
    """Извлечь URL из текста"""
    url_pattern = r'https?://[^\s]+'
    match = re.search(url_pattern, text)
    return match.group(0) if match else ""


async def _process_url(message: Message, url: str, state: FSMContext, template_service: TemplateService):
    """Обработать URL файла"""
    status_message = None
    try:
        # Отправляем сообщение о начале обработки
        status_message = await safe_answer(message, "🔍 Проверяю ссылку...")
        if not status_message:
            logger.warning("Не удалось отправить статусное сообщение")
            return
        
        async with URLService() as url_service:
            # Проверяем поддержку URL
            if not url_service.is_supported_url(url):
                await safe_edit_text(
                    status_message,
                    "❌ Данный тип ссылки не поддерживается.\n\n"
                    "Поддерживаются только:\n"
                    "• Google Drive (drive.google.com)\n"
                    "• Яндекс.Диск (disk.yandex.ru, yadi.sk)"
                )
                return
            
            # Получаем информацию о файле
            await safe_edit_text(status_message, "📊 Получаю информацию о файле...")
            
            try:
                filename, file_size, direct_url = await url_service.get_file_info(url)
                
                # Валидируем файл
                url_service.validate_file_by_info(filename, file_size)
                
                # Отображаем информацию о файле
                size_mb = file_size / (1024 * 1024)
                await safe_edit_text(
                    status_message,
                    f"✅ Файл найден!\n\n"
                    f"📄 Имя: {filename}\n"
                    f"📊 Размер: {size_mb:.1f} МБ\n\n"
                    f"⬇️ Начинаю скачивание..."
                )
                
                # Скачиваем файл (используем уже полученный direct_url, чтобы не делать повторный запрос)
                temp_path = await url_service.download_file(direct_url, filename)
                original_filename = filename
                
                # Сохраняем информацию в состоянии
                await state.update_data(
                    file_path=temp_path,
                    file_name=original_filename,
                    file_url=url,  # Сохраняем оригинальный URL для кеширования
                    is_external_file=True  # Флаг для отличия от Telegram файлов
                )
                
                await safe_edit_text(
                    status_message,
                    f"✅ Файл успешно скачан: {original_filename}"
                )
                
                # Показываем детальное меню добавления участников
                from src.handlers.participants_handlers import show_participants_menu
                from services import UserService
                user_service = UserService()
                await show_participants_menu(message, user_service)
                
            except FileSizeError as e:
                from ux.message_builder import MessageBuilder
                from config import settings
                
                error_details = {
                    "type": "size",
                    "actual_size": file_size,
                    "max_size": settings.max_external_file_size // (1024 * 1024)  # В МБ
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_edit_text(status_message, error_message, parse_mode="Markdown")
                
            except FileTypeError as e:
                from ux.message_builder import MessageBuilder
                
                error_details = {
                    "type": "format",
                    "extension": os.path.splitext(filename)[1] if filename else "",
                    "supported_formats": {
                        "audio": ["MP3", "WAV", "M4A", "OGG"],
                        "video": ["MP4", "AVI", "MOV", "MKV", "WEBM", "FLV"]
                    }
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_edit_text(status_message, error_message, parse_mode="Markdown")
                
            except FileError as e:
                await safe_edit_text(status_message, f"❌ Ошибка при обработке файла: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка при обработке URL {url}: {e}")
        # Используем safe_answer только если не удалось создать status_message
        if not status_message:
            await safe_answer(message, "❌ Произошла ошибка при обработке ссылки. Попробуйте еще раз.")
