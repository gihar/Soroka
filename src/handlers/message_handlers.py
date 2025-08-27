"""
Обработчики сообщений с файлами
"""

import re
import os
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import FileService, TemplateService, OptimizedProcessingService
from services.url_service import URLService
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
    
    @router.message(F.content_type == 'text')
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
                await _show_template_selection(message, template_service)
                
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
