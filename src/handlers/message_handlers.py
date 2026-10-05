"""
Обработчики сообщений с файлами
"""

import os
from typing import Optional

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from src.exceptions.file import FileError, FileSizeError, FileTypeError
from src.exceptions.template import TemplateNotFoundError
from src.handlers.record_state import register_new_record
from src.services import FileService, ProcessingService, TemplateService
from src.services.url_service import URLService
from src.utils.telegram_safe import safe_answer, safe_edit_text
from src.utils.url_detection import contains_url, extract_url
from src.ux.quick_actions import ADMIN_MENU_BUTTON, QuickActionsUI


def _menu_button_texts() -> list[str]:
    """Подписи кнопок главного меню (create_main_menu).

    Единый список зеркалит подписи главного меню: text_handler пропускает эти
    тапы в свой роутер вместо разбора как URL. Вход в админку берётся из общей
    константы ADMIN_MENU_BUTTON, чтобы подпись не разъехалась с кнопкой.
    """
    return [
        "Мои шаблоны", "⚙️ Настройки",
        "Помощь", "Обратная связь",
        ADMIN_MENU_BUTTON,
    ]


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
            except FileSizeError:
                from src.ux.message_builder import MessageBuilder
                error_details = {
                    "type": "size",
                    "actual_size": getattr(file_obj, 'file_size', 0),
                    "max_size": 20
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_answer(message, error_message, parse_mode="HTML")
                return
            except FileTypeError:
                from src.ux.message_builder import MessageBuilder
                formats = file_service.get_supported_formats()
                error_details = {
                    "type": "format",
                    "extension": file_name.split('.')[-1] if '.' in file_name else "",
                    "supported_formats": formats
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_answer(message, error_message, parse_mode="HTML")
                return
            except FileError as e:
                from src.ux.message_builder import MessageBuilder
                error_message = MessageBuilder.error_message("validation", str(e))
                await safe_answer(message, error_message, parse_mode="HTML")
                return
            
            # Проверяем наличие file_id
            if not file_obj.file_id:
                await safe_answer(
                    message,
                    "❌ Не удалось распознать файл.\n"
                    "Отправьте его ещё раз."
                )
                return
            
            # Сохраняем информацию о файле в состоянии, вытесняя прежнюю запись
            await register_new_record(
                state,
                file_id=file_obj.file_id,
                file_name=file_name,
                is_external_file=False,
            )
            
            logger.info(f"Файл сохранен в состояние: file_id={file_obj.file_id}, file_name={file_name}")

            # Меню действий с записью — единая точка правды для файла и ссылки
            text, keyboard = QuickActionsUI.create_record_actions_menu()
            await safe_answer(message, text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Ошибка в media_handler: {e}")
            await safe_answer(
                message,
                "❌ Не получилось принять файл.\n"
                "Отправьте его ещё раз — обычно повторная попытка помогает."
            )
    
    # Обрабатываем текст только когда пользователь НЕ в FSM-состоянии
    @router.message(StateFilter(None), F.content_type == 'text')
    async def text_handler(message: Message, state: FSMContext):
        """Обработчик текстовых сообщений (для URL)"""
        try:
            text = message.text.strip()
            
            # Исключаем обработку кнопок меню - они должны обрабатываться в quick_actions.
            if text in _menu_button_texts():
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
                    "Отправьте файл (аудио или видео) или ссылку на Google Drive/Яндекс.Диск/Synology Drive для обработки.\n\n"
                    "Поддерживаемые форматы:\n"
                    "Аудио: MP3, WAV, M4A, OGG\n"
                    "Видео: MP4, AVI, MOV, MKV"
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
            await safe_answer(
                message,
                "❌ Не получилось обработать сообщение.\n"
                "Отправьте запись или ссылку ещё раз."
            )
    
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


async def _show_template_selection_step2(message: Message, template_service: TemplateService, state: FSMContext = None, participants_count: Optional[int] = None, real_user_id: Optional[int] = None):
    """Показать выбор шаблонов (шаг 2)"""
    try:
        # Меню участников остаётся выше в чате: гасим его кнопки, чтобы тап по
        # устаревшему экрану не уводил в поток, которого уже нет (критика v11).
        from src.handlers.participants_handlers import dismiss_participants_menu

        await dismiss_participants_menu(message.bot, state)

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
        from src.services import UserService
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
            text="Протокол: Умный выбор шаблона",
            callback_data="quick_smart_select"
        )])

        # Кнопка 2: Сохранённый шаблон (если есть)
        if default_template_id is not None:
            default_id = default_template_id
            button_text = None
            try:
                if default_id == 0:
                    button_text = "Протокол: Умный выбор (по умолчанию)"
                else:
                    try:
                        default_template = await template_service.get_template_by_id(default_id)
                        button_text = f"По шаблону: {default_template.name}"
                    except TemplateNotFoundError:
                        button_text = f"По шаблону (ID {default_id})"
                
                if button_text:
                    keyboard_buttons.append([InlineKeyboardButton(
                        text=button_text,
                        callback_data="use_saved_default"
                    )])
            except Exception as e:
                logger.warning(f"Не удалось получить шаблон по умолчанию: {e}")
        
        # Кнопка 4: Выбрать шаблон (для разового использования)
        keyboard_buttons.append([InlineKeyboardButton(
            text="Выбрать шаблон",
            callback_data="select_template_once"
        )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Формируем текст сообщения
        message_text = ""
        
        # Если передано количество участников, добавляем подтверждение
        if participants_count is not None:
            message_text = f"✅ Список участников сохранен ({participants_count} чел.)\n\n"
        
        message_text += (
            "<b>Выберите способ создания протокола:</b>\n\n"
            "<b>Умный выбор</b> - ИИ автоматически подберёт подходящий шаблон\n"
            "<b>По шаблону</b> - использовать сохранённый шаблон\n"
            "<b>Выбрать шаблон</b> - выбрать шаблон для текущей обработки"
        )
        
        await safe_answer(message,
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе шаблонов: {e}")
        await message.answer(
            "❌ Не удалось загрузить шаблоны.\n"
            "Попробуйте ещё раз — если повторится, откройте /templates."
        )


def _contains_url(text: str) -> bool:
    """Проверить, содержит ли текст URL.

    Делегирует общему детектору: фильтр ловца имени в карточке сопоставления
    сходится на том же определении «в сообщении есть ссылка».
    """
    return contains_url(text)


def _extract_url(text: str) -> str:
    """Извлечь URL из текста (общий детектор)."""
    return extract_url(text)


async def _process_url(message: Message, url: str, state: FSMContext, template_service: TemplateService):
    """Обработать URL файла"""
    status_message = None
    try:
        # Отправляем сообщение о начале обработки
        status_message = await safe_answer(message, "Проверяю ссылку...")
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
                    "• Яндекс.Диск (disk.yandex.ru, yadi.sk)\n"
                    "• Synology Drive (публичная ссылка вида https://<хост>/d/s/...)"
                )
                return
            
            # Получаем информацию о файле
            await safe_edit_text(status_message, "Получаю информацию о файле...")
            
            try:
                filename, file_size, direct_url = await url_service.get_file_info(url)
                
                # Валидируем файл
                url_service.validate_file_by_info(filename, file_size)
                
                # Отображаем информацию о файле
                size_mb = file_size / (1024 * 1024)
                await safe_edit_text(
                    status_message,
                    f"✅ Файл найден.\n\n"
                    f"Имя: {filename}\n"
                    f"Размер: {size_mb:.1f} МБ\n\n"
                    f"Начинаю скачивание..."
                )
                
                # Скачиваем файл (используем уже полученный direct_url, чтобы не делать повторный запрос)
                temp_path = await url_service.download_file(direct_url, filename)
                original_filename = filename
                
                # Сохраняем информацию в состоянии, вытесняя прежнюю запись
                await register_new_record(
                    state,
                    file_path=temp_path,
                    file_name=original_filename,
                    file_url=url,  # Сохраняем оригинальный URL для кеширования
                    is_external_file=True,  # Флаг для отличия от Telegram файлов
                )
                
                await safe_edit_text(
                    status_message,
                    f"✅ Файл успешно скачан: {original_filename}"
                )

                # Меню действий с записью — то же, что и для файла (единая точка правды)
                text, keyboard = QuickActionsUI.create_record_actions_menu()
                await safe_answer(message, text, reply_markup=keyboard, parse_mode="HTML")
                
            except FileSizeError:
                from src.config import settings
                from src.ux.message_builder import MessageBuilder
                
                error_details = {
                    "type": "size",
                    "actual_size": file_size,
                    "max_size": settings.max_external_file_size // (1024 * 1024)  # В МБ
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_edit_text(status_message, error_message, parse_mode="HTML")
                
            except FileTypeError:
                from src.ux.message_builder import MessageBuilder
                
                error_details = {
                    "type": "format",
                    "extension": os.path.splitext(filename)[1] if filename else "",
                    "supported_formats": {
                        "audio": ["MP3", "WAV", "M4A", "OGG"],
                        "video": ["MP4", "AVI", "MOV", "MKV", "WEBM", "FLV"]
                    }
                }
                error_message = MessageBuilder.file_validation_error(error_details)
                await safe_edit_text(status_message, error_message, parse_mode="HTML")
                
            except FileError as e:
                logger.warning(f"Не удалось обработать файл по ссылке {url}: {e}")
                await safe_edit_text(
                    status_message,
                    "❌ Не получилось обработать файл по ссылке.\n"
                    "Проверьте, что файл доступен для скачивания, и пришлите ссылку ещё раз."
                )

    except Exception as e:
        logger.error(f"Ошибка при обработке URL {url}: {e}")
        # Используем safe_answer только если не удалось создать status_message
        if not status_message:
            await safe_answer(
                message,
                "❌ Не получилось обработать ссылку.\n"
                "Проверьте доступ по ссылке и отправьте её ещё раз."
            )
