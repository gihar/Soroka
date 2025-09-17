"""
Обработчики сообщений с файлами
"""

import re
import os
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import FileService, TemplateService, OptimizedProcessingService
from services.url_service import URLService
from src.exceptions.file import FileError, FileSizeError, FileTypeError


def setup_message_handlers(file_service: FileService, template_service: TemplateService,
                          processing_service: OptimizedProcessingService) -> Router:
    """Настройка обработчиков сообщений"""
    router = Router()
    
    @router.message(F.content_type.in_({'audio', 'video', 'voice', 'video_note', 'document'}))
    async def media_handler(message: Message, state: FSMContext):
        """Обработчик медиа файлов"""
        try:
            # Определяем тип и получаем файл
            file_obj, file_name, content_type = _extract_file_info(message)
            
            if not file_obj:
                await message.answer("❌ Не удалось обработать файл. Попробуйте отправить файл еще раз.")
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
                await message.answer(error_message, parse_mode="Markdown")
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
                await message.answer(error_message, parse_mode="Markdown")
                return
            except FileError as e:
                from ux.message_builder import MessageBuilder
                error_message = MessageBuilder.error_message("validation", str(e))
                await message.answer(error_message, parse_mode="Markdown")
                return
            
            # Проверяем наличие file_id
            if not file_obj.file_id:
                await message.answer(
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
            
            # Показываем шаблоны для выбора
            await _show_template_selection(message, template_service, state)
            
        except Exception as e:
            logger.error(f"Ошибка в media_handler: {e}")
            await message.answer("❌ Произошла ошибка при обработке файла. Попробуйте еще раз.")
    
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
                await message.answer(
                    "📎 Отправьте файл (аудио или видео) или ссылку на Google Drive/Яндекс.Диск для обработки.\n\n"
                    "Поддерживаемые форматы:\n"
                    "🎵 Аудио: MP3, WAV, M4A, OGG\n"
                    "🎬 Видео: MP4, AVI, MOV, MKV"
                )
                return
            
            # Извлекаем URL из сообщения
            url = _extract_url(text)
            if not url:
                await message.answer("❌ Не удалось найти корректную ссылку в сообщении.")
                return
            
            # Обрабатываем URL
            await _process_url(message, url, state, template_service)
            
        except Exception as e:
            logger.error(f"Ошибка в text_handler: {e}")
            await message.answer("❌ Произошла ошибка при обработке сообщения. Попробуйте еще раз.")
    
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
    
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        
        # Проверяем наличие обязательных данных
        if not data.get('template_id') or not data.get('llm_provider'):
            await message.answer(
                "❌ Ошибка: отсутствуют обязательные данные. Пожалуйста, повторите процесс."
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
            template_id=data['template_id'],
            llm_provider=data['llm_provider'],
            user_id=message.from_user.id,
            language="ru",
            is_external_file=is_external_file
        )
        
        # Создаем прогресс-трекер
        from ux.progress_tracker import ProgressFactory
        from ux.message_builder import MessageBuilder
        from ux.feedback_system import QuickFeedbackManager, feedback_collector
        from config import settings
        
        progress_tracker = await ProgressFactory.create_file_processing_tracker(
            message.bot, message.chat.id, settings.enable_diarization
        )
        
        try:
            # Обрабатываем файл с отображением прогресса
            result = await processing_service.process_file(request, progress_tracker)

            await progress_tracker.complete_all()

            # Определяем красивое имя модели для отображения
            llm_model_name = result.llm_provider_used
            try:
                if result.llm_provider_used == 'openai':
                    from config import settings as app_settings
                    from src.services.user_service import UserService
                    user_service = UserService()
                    user = await user_service.get_user_by_telegram_id(message.from_user.id)
                    selected_key = getattr(user, 'preferred_openai_model_key', None) if user else None
                    preset = None
                    if selected_key:
                        preset = next((p for p in getattr(app_settings, 'openai_models', []) if p.key == selected_key), None)
                    if not preset:
                        models = getattr(app_settings, 'openai_models', [])
                        if models:
                            preset = models[0]
                    if preset:
                        llm_model_name = preset.name
            except Exception:
                # В случае ошибок оставляем провайдера по умолчанию
                pass

            # Показываем результат с улучшенным форматированием
            result_dict = {
                "template_used": {"name": result.template_used.get('name', 'Неизвестный')},
                "llm_provider_used": result.llm_provider_used,
                "llm_model_name": llm_model_name,
                "processing_time": result.processing_duration,
                "file_name": result.transcription_result.transcription[:100] + "..." if len(result.transcription_result.transcription) > 100 else result.transcription_result.transcription,
                "summary": result.protocol_text,
                "key_points": [],  # Будет заполнено из протокола
                "action_items": [],  # Будет заполнено из протокола
                "sentiment": "neutral",  # По умолчанию
                "language": "ru",
                "word_count": len(result.transcription_result.transcription.split()),
                "speaker_count": len(result.transcription_result.speakers_text) if result.transcription_result.speakers_text else 1,
                "confidence_score": 0.9  # По умолчанию
            }
            
            # Создаем сообщение с результатом
            result_message = MessageBuilder.processing_complete_message(result_dict)
            
            # Отправляем результат
            await message.answer(result_message, parse_mode="Markdown")
            
            # Отправляем протокол согласно пользовательской настройке
            if not result.protocol_text:
                logger.warning("protocol_text пустой или None")
                await message.answer("❌ Протокол не был сгенерирован")
            else:
                try:
                    from src.services.user_service import UserService as _US
                    user_pref_service = _US()
                    user = await user_pref_service.get_user_by_telegram_id(message.from_user.id)
                    output_mode = getattr(user, 'protocol_output_mode', None) or 'messages'

                    if output_mode == 'file':
                        import tempfile
                        from aiogram.types import FSInputFile
                        suffix = '.md'
                        safe_name = 'protocol'
                        try:
                            original = result.transcription_result and data.get('file_name') or 'protocol'
                            import os
                            safe_name = os.path.splitext(os.path.basename(original))[0][:40] or 'protocol'
                        except Exception:
                            pass
                        with tempfile.NamedTemporaryFile('w', suffix=suffix, delete=False, encoding='utf-8') as f:
                            f.write(result.protocol_text or '')
                            temp_path = f.name
                        try:
                            file_input = FSInputFile(temp_path, filename=f"{safe_name}.md")
                            await message.answer_document(
                                file_input,
                                caption="📎 Протокол встречи"
                            )
                        finally:
                            import os
                            try:
                                os.unlink(temp_path)
                            except Exception:
                                pass
                    else:
                        # В сообщения: разбиваем при необходимости
                        protocol_length = len(result.protocol_text)
                        logger.info(f"Длина протокола: {protocol_length} символов")
                        logger.info(f"Тип protocol_text: {type(result.protocol_text)}")
                        if protocol_length > 4000:
                            logger.info(f"Протокол длинный ({protocol_length} символов), разбиваем на части")
                            await _send_long_protocol(message, result.protocol_text)
                        else:
                            logger.info(f"Протокол короткий ({protocol_length} символов), отправляем как есть")
                            await message.answer(result.protocol_text, parse_mode="Markdown")
                except Exception as send_err:
                    logger.error(f"Ошибка при отправке протокола: {send_err}")
                    await message.answer("⚠️ Не удалось отправить протокол. Попробуйте позже.")
            
            # Показываем кнопки быстрой обратной связи
            from ux.feedback_system import feedback_collector
            feedback_manager = QuickFeedbackManager(feedback_collector)
            await feedback_manager.request_quick_feedback(message.chat.id, message.bot, result_dict)
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка при обработке файла: {e}")
            await progress_tracker.complete_all()
            await message.answer(
                "❌ Произошла ошибка при обработке файла. Попробуйте еще раз или обратитесь к администратору."
            )
            await state.clear()
            
    except Exception as e:
        logger.error(f"Ошибка при создании запроса на обработку: {e}")
        await message.answer("❌ Произошла ошибка при подготовке обработки файла.")
        await state.clear()


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


async def _show_template_selection(message: Message, template_service: TemplateService, state: FSMContext = None):
    """Показать выбор шаблонов"""
    try:
        # Проверяем, есть ли у пользователя шаблон по умолчанию
        from services import UserService
        user_service = UserService()
        user = await user_service.get_user_by_telegram_id(message.from_user.id)
        
        # Если у пользователя есть шаблон по умолчанию, автоматически используем его
        if user and user.default_template_id and state:
            try:
                default_template = await template_service.get_template_by_id(user.default_template_id)
                if default_template:
                    # Сохраняем шаблон в состоянии
                    await state.update_data(template_id=default_template.id)
                    
                    await message.answer(
                        f"🚀 **Обработка по выбранному шаблону: {default_template.name}**",
                        parse_mode="Markdown"
                    )
                    
                    # Показываем выбор LLM
                    from services import EnhancedLLMService, OptimizedProcessingService
                    llm_service = EnhancedLLMService()
                    processing_service = OptimizedProcessingService()
                    
                    # Показываем выбор LLM для обработки
                    await _show_llm_selection_for_file(message, state, llm_service, processing_service)
                    
                    return
            except Exception as e:
                logger.warning(f"Не удалось получить шаблон по умолчанию: {e}")
                # Продолжаем с обычным выбором шаблонов
        
        # Показываем все доступные шаблоны
        templates = await template_service.get_all_templates()
        
        if not templates:
            await message.answer("❌ Шаблоны не найдены. Обратитесь к администратору.")
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                callback_data=f"select_template_{t.id}"
            )]
            for t in templates
        ])
        
        await message.answer(
            "📝 Выберите шаблон для протокола:",
            reply_markup=keyboard
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
    try:
        # Отправляем сообщение о начале обработки
        status_message = await message.answer("🔍 Проверяю ссылку...")
        
        async with URLService() as url_service:
            # Проверяем поддержку URL
            if not url_service.is_supported_url(url):
                await status_message.edit_text(
                    "❌ Данный тип ссылки не поддерживается.\n\n"
                    "Поддерживаются только:\n"
                    "• Google Drive (drive.google.com)\n"
                    "• Яндекс.Диск (disk.yandex.ru, yadi.sk)"
                )
                return
            
            # Получаем информацию о файле
            await status_message.edit_text("📊 Получаю информацию о файле...")
            
            try:
                filename, file_size, direct_url = await url_service.get_file_info(url)
                
                # Валидируем файл
                url_service.validate_file_by_info(filename, file_size)
                
                # Отображаем информацию о файле
                size_mb = file_size / (1024 * 1024)
                await status_message.edit_text(
                    f"✅ Файл найден!\n\n"
                    f"📄 Имя: {filename}\n"
                    f"📊 Размер: {size_mb:.1f} МБ\n\n"
                    f"⬇️ Начинаю скачивание..."
                )
                
                # Скачиваем файл
                temp_path, original_filename = await url_service.process_url(url)
                
                # Сохраняем информацию в состоянии
                await state.update_data(
                    file_path=temp_path,
                    file_name=original_filename,
                    is_external_file=True  # Флаг для отличия от Telegram файлов
                )
                
                await status_message.edit_text(
                    f"✅ Файл успешно скачан: {original_filename}"
                )
                
                # Показываем шаблоны для выбора
                await _show_template_selection(message, template_service, state)
                
            except FileSizeError as e:
                from ux.message_builder import MessageBuilder
                from config import settings
                
                error_details = {
                    "type": "size",
                    "actual_size": file_size,
                    "max_size": settings.max_external_file_size // (1024 * 1024)  # В МБ
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await status_message.edit_text(error_message, parse_mode="Markdown")
                
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
                await status_message.edit_text(error_message, parse_mode="Markdown")
                
            except FileError as e:
                await status_message.edit_text(f"❌ Ошибка при обработке файла: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка при обработке URL {url}: {e}")
        await message.answer("❌ Произошла ошибка при обработке ссылки. Попробуйте еще раз.")
