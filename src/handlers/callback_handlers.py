"""
Обработчики callback запросов
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, OptimizedProcessingService


def setup_callback_handlers(user_service: UserService, template_service: TemplateService,
                           llm_service: EnhancedLLMService, processing_service: OptimizedProcessingService) -> Router:
    """Настройка обработчиков callback запросов"""
    router = Router()
    
    @router.callback_query(F.data.startswith("set_llm_"))
    async def set_llm_callback(callback: CallbackQuery):
        """Обработчик выбора LLM"""
        try:
            llm_provider = callback.data.replace("set_llm_", "")
            
            await user_service.update_user_llm_preference(callback.from_user.id, llm_provider)
            
            available_providers = llm_service.get_available_providers()
            provider_name = available_providers.get(llm_provider, llm_provider)
            
            await callback.message.edit_text(
                f"✅ LLM провайдер изменен на: {provider_name}\n\n"
                f"Теперь этот LLM будет использоваться автоматически для всех обработок."
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в set_llm_callback: {e}")
            await callback.answer("❌ Произошла ошибка при изменении настроек")
    
    @router.callback_query(F.data == "reset_llm_preference")
    async def reset_llm_preference_callback(callback: CallbackQuery):
        """Обработчик сброса предпочтений LLM"""
        try:
            await user_service.update_user_llm_preference(callback.from_user.id, None)
            
            await callback.message.edit_text(
                "🔄 Предпочтения LLM сброшены.\n\n"
                "Теперь бот будет спрашивать выбор LLM при каждой обработке файла."
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в reset_llm_preference_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе настроек")
    
    @router.callback_query(F.data.startswith("select_template_"))
    async def select_template_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора шаблона"""
        try:
            template_id = int(callback.data.replace("select_template_", ""))
            await state.update_data(template_id=template_id)
            
            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)
            
        except Exception as e:
            logger.error(f"Ошибка в select_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при выборе шаблона")
    
    @router.callback_query(F.data.startswith("select_llm_"))
    async def select_llm_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора LLM для обработки"""
        try:
            llm_provider = callback.data.replace("select_llm_", "")
            
            # Сохраняем выбор пользователя как предпочтение
            await user_service.update_user_llm_preference(callback.from_user.id, llm_provider)
            await state.update_data(llm_provider=llm_provider)
            
            # Начинаем обработку
            await _process_file(callback, state, processing_service)
            
        except Exception as e:
            logger.error(f"Ошибка в select_llm_callback: {e}")
            await callback.answer("❌ Произошла ошибка при выборе LLM")
    
    @router.callback_query(F.data.startswith("view_template_"))
    async def view_template_callback(callback: CallbackQuery):
        """Обработчик просмотра шаблона"""
        try:
            template_id = int(callback.data.replace("view_template_", ""))
            template = await template_service.get_template_by_id(template_id)
            
            text = f"📝 **{template.name}**\n\n"
            if template.description:
                text += f"*Описание:* {template.description}\n\n"
            
            text += f"```\n{template.content}\n```"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад к списку шаблонов",
                    callback_data="back_to_templates"
                )]
            ])
            
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в view_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при просмотре шаблона")
    
    @router.callback_query(F.data == "back_to_templates")
    async def back_to_templates_callback(callback: CallbackQuery):
        """Возврат к списку шаблонов"""
        try:
            templates = await template_service.get_all_templates()
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"view_template_{t.id}"
                )]
                for t in templates
            ] + [
                [InlineKeyboardButton(
                    text="➕ Добавить шаблон",
                    callback_data="add_template"
                )]
            ])
            
            await callback.message.edit_text(
                "📝 **Доступные шаблоны:**",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в back_to_templates_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке шаблонов")
    
    return router


async def _show_llm_selection(callback: CallbackQuery, state: FSMContext, 
                             user_service: UserService, llm_service: EnhancedLLMService,
                             processing_service: OptimizedProcessingService):
    """Показать выбор LLM или использовать сохранённые предпочтения"""
    user = await user_service.get_user_by_telegram_id(callback.from_user.id)
    available_providers = llm_service.get_available_providers()
    
    if not available_providers:
        await callback.message.edit_text(
            "❌ Нет доступных LLM провайдеров. "
            "Проверьте конфигурацию API ключей."
        )
        return
    
    # Проверяем, есть ли у пользователя сохранённые предпочтения
    if user and user.preferred_llm is not None:
        preferred_llm = user.preferred_llm
        # Проверяем, что предпочитаемый LLM доступен
        if preferred_llm in available_providers:
            # Сохраняем в состояние и сразу переходим к обработке
            await state.update_data(llm_provider=preferred_llm)
            await callback.message.edit_text(
                f"🤖 Используется сохранённый LLM: {available_providers[preferred_llm]}\n\n"
                "⏳ Начинаю обработку..."
            )
            await _process_file(callback, state, processing_service)
            return
    
    # Если предпочтений нет или предпочитаемый LLM недоступен, показываем выбор
    current_llm = user.preferred_llm if user else 'openai'
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅ ' if provider_key == current_llm else ''}{provider_name}",
            callback_data=f"select_llm_{provider_key}"
        )]
        for provider_key, provider_name in available_providers.items()
    ])
    
    await callback.message.edit_text(
        "🤖 Выберите LLM для обработки:",
        reply_markup=keyboard
    )


async def _process_file(callback: CallbackQuery, state: FSMContext, processing_service: OptimizedProcessingService):
    """Начать обработку файла"""
    from src.models.processing import ProcessingRequest
    
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        
        # Проверяем наличие обязательных данных
        if not data.get('template_id') or not data.get('llm_provider'):
            await callback.message.edit_text(
                "❌ Ошибка: отсутствуют обязательные данные. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return
        
        # Проверяем, что есть либо file_id (для Telegram файлов), либо file_path (для внешних файлов)
        is_external_file = data.get('is_external_file', False)
        if is_external_file:
            if not data.get('file_path') or not data.get('file_name'):
                await callback.message.edit_text(
                    "❌ Ошибка: отсутствуют данные о внешнем файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return
        else:
            if not data.get('file_id') or not data.get('file_name'):
                await callback.message.edit_text(
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
            user_id=callback.from_user.id,
            language="ru",
            is_external_file=is_external_file
        )
        
        # Создаем прогресс-трекер
        from ux.progress_tracker import ProgressFactory
        from ux.message_builder import MessageBuilder
        from ux.feedback_system import QuickFeedbackManager, feedback_collector
        # Используем прямую интеграцию с оптимизированным сервисом
        from config import settings
        
        progress_tracker = await ProgressFactory.create_file_processing_tracker(
            callback.bot, callback.message.chat.id, settings.enable_diarization
        )
        
        try:
            # Обрабатываем файл с отображением прогресса
            result = await processing_service.process_file(request, progress_tracker)
            
            await progress_tracker.complete_all()
            
            # Показываем результат с улучшенным форматированием
            result_dict = {
                "template_used": {"name": result.template_used.get('name', 'Неизвестный')},
                "llm_provider_used": result.llm_provider_used,
                "transcription_result": {
                    "transcription": result.transcription_result.transcription,
                    "diarization": result.transcription_result.diarization
                },
                "processing_duration": result.processing_duration
            }
            
            result_message = MessageBuilder.processing_complete_message(result_dict)
            
            # Отправляем сообщение о завершении с обработкой ошибок длины
            try:
                await callback.bot.send_message(
                    callback.message.chat.id,
                    result_message,
                    parse_mode="Markdown"
                )
            except Exception as e:
                if "message is too long" in str(e).lower():
                    # Если сообщение слишком длинное, отправляем без Markdown
                    await callback.bot.send_message(
                        callback.message.chat.id,
                        result_message
                    )
                else:
                    raise e
            
            # Отправляем протокол с обработкой ошибок
            try:
                await _send_long_message(callback.message.chat.id, result.protocol_text, callback.bot)
            except Exception as e:
                logger.error(f"Ошибка отправки протокола: {e}")
                # Отправляем уведомление об ошибке
                await callback.bot.send_message(
                    callback.message.chat.id,
                    "⚠️ Протокол слишком длинный для отправки. Попробуйте обработать файл меньшего размера."
                )
            
            # Запрашиваем обратную связь
            feedback_manager = QuickFeedbackManager(feedback_collector)
            await feedback_manager.request_quick_feedback(
                callback.message.chat.id, callback.bot, result_dict
            )
            
        except Exception as e:
            logger.error(f"Ошибка при обработке файла: {e}")
            
            # Специальная обработка ошибок размера файла
            error_message = str(e)
            if "message is too long" in error_message.lower():
                user_message = (
                    "📄 **Сообщение слишком длинное**\n\n"
                    "Результат обработки превышает лимит Telegram. Попробуйте:\n\n"
                    "• Обработать файл меньшего размера\n"
                    "• Разделить длинную запись на части\n"
                    "• Использовать более короткий аудиофайл"
                )
            elif "too large" in error_message.lower() or "413" in error_message:
                user_message = (
                    "📦 **Файл слишком большой для облачной транскрипции**\n\n"
                    "Система автоматически переключилась на локальную транскрипцию, "
                    "но произошла ошибка. Попробуйте:\n\n"
                    "• Сжать аудиофайл до меньшего размера\n"
                    "• Разделить длинную запись на несколько частей\n"
                    "• Использовать формат с лучшим сжатием (MP3)\n"
                    "• Снизить качество аудио"
                )
            elif "transcription" in error_message.lower():
                user_message = (
                    "🎤 **Ошибка при транскрипции**\n\n"
                    f"Детали: {error_message}\n\n"
                    "Попробуйте:\n"
                    "• Проверить качество аудио\n"
                    "• Убедиться, что файл не поврежден\n"
                    "• Попробовать другой аудиофайл"
                )
            else:
                user_message = f"❌ **Ошибка при обработке файла**\n\n{error_message}"
            
            await progress_tracker.error("processing", user_message)
            
            # Отправляем сообщение пользователю
            await callback.bot.send_message(
                callback.message.chat.id,
                user_message,
                parse_mode="Markdown"
            )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        await callback.message.edit_text(f"❌ Ошибка при обработке файла: {e}")
    finally:
        await state.clear()


async def _send_long_message(chat_id: int, text: str, bot, max_length: int = 4096):
    """Отправить длинное сообщение по частям"""
    # Учитываем заголовок при расчете максимальной длины части
    header_template = "📄 **Протокол встречи** (часть {}/{})\n\n"
    max_header_length = len(header_template.format(999, 999))  # Максимальная длина заголовка
    max_part_length = max_length - max_header_length
    
    if len(text) <= max_length:
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
            return
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            # Если не удалось отправить с Markdown, пробуем без него
            await bot.send_message(chat_id, text)
            return
    
    # Разбиваем текст на части
    parts = []
    current_part = ""
    
    for line in text.split('\n'):
        if len(current_part) + len(line) + 1 <= max_part_length:
            current_part += line + '\n'
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + '\n'
    
    if current_part:
        parts.append(current_part.strip())
    
    # Отправляем части с обработкой ошибок
    for i, part in enumerate(parts):
        try:
            header = f"📄 **Протокол встречи** (часть {i+1}/{len(parts)})\n\n"
            full_message = header + part
            
            # Проверяем, что сообщение не превышает лимит
            if len(full_message) > max_length:
                # Если превышает, отправляем без Markdown
                await bot.send_message(chat_id, full_message)
            else:
                await bot.send_message(chat_id, full_message, parse_mode="Markdown")
                
        except Exception as e:
            logger.error(f"Ошибка отправки части {i+1}: {e}")
            # Пробуем отправить без Markdown
            try:
                header = f"📄 Протокол встречи (часть {i+1}/{len(parts)})\n\n"
                await bot.send_message(chat_id, header + part)
            except Exception as e2:
                logger.error(f"Критическая ошибка отправки части {i+1}: {e2}")
                # Отправляем простой текст без заголовка
                await bot.send_message(chat_id, part[:max_length])
