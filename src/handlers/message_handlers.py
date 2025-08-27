"""
Обработчики сообщений с файлами
"""

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import FileService, TemplateService, OptimizedProcessingService
from exceptions import FileError, FileSizeError, FileTypeError


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
            await _show_template_selection(message, template_service)
            
        except Exception as e:
            logger.error(f"Ошибка в media_handler: {e}")
            await message.answer("❌ Произошла ошибка при обработке файла. Попробуйте еще раз.")
    
    return router


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


async def _show_template_selection(message: Message, template_service: TemplateService):
    """Показать выбор шаблонов"""
    try:
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
