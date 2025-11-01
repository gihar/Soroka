"""
Обработчики для работы со списком участников встречи
"""

import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from loguru import logger

from src.handlers.participants_states import ParticipantsInput
from src.services.participants_service import participants_service
from src.services.user_service import UserService
from src.exceptions.file import FileError


def setup_participants_handlers() -> Router:
    """Настройка обработчиков для работы с участниками"""
    router = Router()
    user_service = UserService()
    
    @router.callback_query(F.data == "add_participants")
    async def start_participants_input(callback: CallbackQuery, state: FSMContext):
        """Начало ввода списка участников"""
        try:
            await callback.answer()
            
            # Проверяем, есть ли сохраненный список у пользователя
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            
            keyboard_buttons = []
            
            # Кнопка для ввода нового списка
            keyboard_buttons.append([InlineKeyboardButton(
                text="✍️ Ввести новый список",
                callback_data="input_new_participants"
            )])
            
            # Если есть сохраненный список - показываем кнопку
            if user and user.saved_participants:
                try:
                    saved = participants_service.participants_from_json(user.saved_participants)
                    if saved:
                        keyboard_buttons.append([InlineKeyboardButton(
                            text=f"📋 Использовать сохраненный ({len(saved)} чел.)",
                            callback_data="use_saved_participants"
                        )])
                except Exception:
                    pass
            
            # Кнопка для загрузки файла
            keyboard_buttons.append([InlineKeyboardButton(
                text="📎 Загрузить файл (.txt, .csv)",
                callback_data="upload_participants_file"
            )])
            
            # Кнопка автоматического извлечения
            keyboard_buttons.append([InlineKeyboardButton(
                text="🔍 Автоматически извлечь из текста",
                callback_data="auto_extract_meeting_info"
            )])

            # Кнопка пропуска
            keyboard_buttons.append([InlineKeyboardButton(
                text="⏭ Пропустить (без имен)",
                callback_data="skip_participants"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            message_text = (
                "👥 **Добавление участников встречи**\n\n"
                "Вы можете указать список участников для более точного протокола. "
                "ИИ автоматически сопоставит говорящих с участниками.\n\n"
                "**Способы добавления:**\n\n"
                "🔍 **Автоматически извлечь** - из email или текста с информацией о встрече\n\n"
                "📝 **Ручной ввод** - текст или файл:\n"
                "• Текст (один участник на строку):\n"
                "  `Иван Петров, менеджер`\n"
                "  `Мария Иванова`\n\n"
                "• Файл .txt или .csv\n\n"
                "Выберите действие:"
            )
            
            await callback.message.answer(
                message_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при начале ввода участников: {e}")
            await callback.message.answer(
                "❌ Произошла ошибка. Попробуйте еще раз."
            )
    
    @router.callback_query(F.data == "auto_extract_meeting_info")
    async def prompt_auto_extraction(callback: CallbackQuery, state: FSMContext):
        """Запрос автоматического извлечения информации о встрече"""
        try:
            await callback.answer()
            await state.set_state(ParticipantsInput.waiting_for_participants)

            # Создаем клавиатуру с кнопками навигации
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="add_participants")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_participants")]
            ])

            await callback.message.answer(
                "🔍 **Автоматическое извлечение информации о встрече**\n\n"
                "Отправьте текст с информацией о встрече (email, сообщение, описание).\n\n"
                "**Поддерживаемые форматы:**\n"
                "• Email с полями От, Кому, Копия, Тема, Когда\n"
                "• Текст с информацией об участниках, дате и теме\n\n"
                "**Пример:**\n"
                "```\n"
                "От: Иван Петров\n"
                "Кому: Мария Иванова; Алексей Смирнов\n"
                "Тема: Обсуждение проекта\n"
                "Когда: 22 октября 2025 г. 15:00-16:00\n"
                "```",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Ошибка при запросе автоизвлечения: {e}")
            await callback.message.answer("❌ Произошла ошибка.")

    @router.callback_query(F.data == "input_new_participants")
    async def prompt_participants_input(callback: CallbackQuery, state: FSMContext):
        """Запрос ввода нового списка участников"""
        try:
            await callback.answer()
            await state.set_state(ParticipantsInput.waiting_for_participants)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="add_participants")]
            ])

            await callback.message.answer(
                "📝 **Введите список участников**\n\n"
                "Отправьте список участников текстом (один участник на строку).\n\n"
                "**Примеры форматов:**\n"
                "• `Иван Петров, руководитель`\n"
                "• `Мария Иванова - разработчик`\n"
                "• `Алексей Смирнов (тестировщик)`\n"
                "• `Ольга Сидорова`\n\n"
                "Или отправьте /cancel для отмены.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Ошибка при запросе ввода участников: {e}")
            await callback.message.answer("❌ Произошла ошибка.")
    
    @router.callback_query(F.data == "upload_participants_file")
    async def prompt_file_upload(callback: CallbackQuery, state: FSMContext):
        """Запрос загрузки файла с участниками"""
        try:
            await callback.answer()
            await state.set_state(ParticipantsInput.waiting_for_participants)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="add_participants")]
            ])
            
            await callback.message.answer(
                "📎 **Загрузите файл с участниками**\n\n"
                "Отправьте файл в формате .txt или .csv\n\n"
                "**Формат .txt:**\n"
                "```\n"
                "Иван Петров, менеджер\n"
                "Мария Иванова\n"
                "```\n\n"
                "**Формат .csv:**\n"
                "```\n"
                "name,role\n"
                "Иван Петров,менеджер\n"
                "Мария Иванова,\n"
                "```\n\n"
                "Или отправьте /cancel для отмены.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при запросе файла: {e}")
            await callback.message.answer("❌ Произошла ошибка.")
    
    @router.callback_query(F.data == "use_saved_participants")
    async def use_saved_participants(callback: CallbackQuery, state: FSMContext):
        """Использование сохраненного списка участников"""
        try:
            await callback.answer()
            
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            
            if not user or not user.saved_participants:
                await callback.message.answer(
                    "❌ У вас нет сохраненного списка участников."
                )
                return
            
            # Загружаем сохраненный список
            participants = participants_service.participants_from_json(user.saved_participants)
            
            if not participants:
                await callback.message.answer(
                    "❌ Не удалось загрузить сохраненный список."
                )
                return
            
            # Сохраняем в состояние
            await state.update_data(participants_list=participants)
            
            # Показываем подтверждение
            display_text = participants_service.format_participants_for_display(participants)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Использовать", callback_data="confirm_participants")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="add_participants")]
            ])
            
            await callback.message.answer(
                f"{display_text}\n\n**Использовать этот список?**",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке сохраненного списка: {e}")
            await callback.message.answer("❌ Произошла ошибка.")
    
    @router.callback_query(F.data == "skip_participants")
    async def skip_participants(callback: CallbackQuery, state: FSMContext):
        """Пропуск добавления участников"""
        try:
            await callback.answer("Участники не будут добавлены")
            
            # Очищаем участников из состояния
            await state.update_data(participants_list=None)
            
            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state)
            
        except Exception as e:
            logger.error(f"Ошибка при пропуске участников: {e}")
            await callback.message.answer("❌ Произошла ошибка.")
    
    @router.message(ParticipantsInput.waiting_for_participants, F.content_type == "text")
    async def handle_participants_text(message: Message, state: FSMContext):
        """Обработка текстового ввода списка участников"""
        try:
            text = message.text.strip()

            # Проверка на команду отмены
            if text.startswith('/cancel'):
                await state.clear()
                await message.answer("❌ Ввод участников отменен.")
                return

            # Гибридный подход: пробуем автоизвлечение, затем обычный парсинг
            meeting_info = participants_service.extract_from_meeting_text(text)
            
            # Всегда парсим весь текст как обычный список участников
            text_participants = participants_service.parse_participants_text(text)
            
            # Объединяем участников из обоих источников
            all_participants = []
            participants_dict = {}  # Для избежания дубликатов по имени
            
            # Добавляем участников из meeting_info (если есть)
            if meeting_info and meeting_info.participants:
                for participant in meeting_info.participants:
                    key = participant.name.lower().strip()
                    if key not in participants_dict:
                        participants_dict[key] = {
                            "name": participant.name,
                            "role": participant.role or ""
                        }
                        all_participants.append(participants_dict[key])
            
            # Добавляем участников из обычного парсинга
            for participant in text_participants:
                key = participant["name"].lower().strip()
                if key not in participants_dict:
                    participants_dict[key] = participant
                    all_participants.append(participant)

            # Проверяем, есть ли участники
            if not all_participants:
                await message.answer(
                    f"❌ **Ошибка извлечения:**\nНе удалось найти участников встречи\n\n"
                    f"Попробуйте другой текст или отправьте /cancel для отмены.",
                    parse_mode="Markdown"
                )
                return

            # Валидируем объединенный список
            is_valid, error_message = participants_service.validate_participants(all_participants)
            if not is_valid:
                await message.answer(
                    f"❌ **Ошибка валидации:**\n{error_message}\n\n"
                    f"Попробуйте еще раз или отправьте /cancel для отмены.",
                    parse_mode="Markdown"
                )
                return

            # Если есть информация о встрече (тема/дата), используем её
            if meeting_info and (meeting_info.topic or meeting_info.start_time):
                # Сохраняем информацию о встрече в состояние
                await state.update_data(meeting_info=meeting_info.model_dump())
                await state.update_data(participants_list=all_participants)

                # Сохраняем тему и дату для использования в промптах
                if meeting_info.topic:
                    await state.update_data(meeting_topic=meeting_info.topic)
                if meeting_info.start_time:
                    await state.update_data(meeting_date=meeting_info.start_time.strftime("%d.%m.%Y"))
                    await state.update_data(meeting_time=meeting_info.start_time.strftime("%H:%M"))

                await state.set_state(ParticipantsInput.confirm_meeting_info)

                # Показываем извлеченную информацию
                display_text = participants_service.format_meeting_info_for_display(meeting_info)
                
                # Добавляем предупреждение если есть
                warning_text = ""
                if meeting_info.topic == "Не указана":
                    warning_text = "\n\n⚠️ Тема встречи не указана, будет использовано значение по умолчанию"

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Использовать", callback_data="confirm_meeting_info"),
                        InlineKeyboardButton(text="💾 Сохранить и использовать", callback_data="save_meeting_info")
                    ],
                    [
                        InlineKeyboardButton(text="⬅️ Назад", callback_data="input_new_participants"),
                        InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")
                    ]
                ])

                await message.answer(
                    f"🔍 **Автоматически извлечена информация о встрече:**\n\n"
                    f"{display_text}{warning_text}\n\n**Использовать эту информацию?**",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

            else:
                # Обычный список участников без информации о встрече
                await state.update_data(participants_list=all_participants)
                await state.set_state(ParticipantsInput.confirm_participants)

                # Показываем для подтверждения
                display_text = participants_service.format_participants_for_display(all_participants)

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_participants"),
                        InlineKeyboardButton(text="💾 Сохранить и использовать", callback_data="save_and_confirm_participants")
                    ],
                    [
                        InlineKeyboardButton(text="⬅️ Назад", callback_data="input_new_participants"),
                        InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")
                    ]
                ])

                await message.answer(
                    f"{display_text}\n\n**Все верно?**",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

        except Exception as e:
            logger.error(f"Ошибка при обработке текста участников: {e}")
            await message.answer(
                "❌ Произошла ошибка при обработке списка. Попробуйте еще раз."
            )
    
    @router.message(ParticipantsInput.waiting_for_participants, F.content_type == "document")
    async def handle_participants_file(message: Message, state: FSMContext):
        """Обработка файла со списком участников"""
        try:
            document = message.document
            
            # Проверяем расширение файла
            file_name = document.file_name or "file"
            file_ext = os.path.splitext(file_name)[1].lower()
            
            if file_ext not in ['.txt', '.csv', '.text']:
                await message.answer(
                    "❌ Поддерживаются только файлы .txt и .csv\n"
                    "Попробуйте еще раз."
                )
                return
            
            # Скачиваем файл
            temp_file_path = f"temp/participants_{message.from_user.id}_{file_ext}"
            
            try:
                await message.bot.download(document, destination=temp_file_path)
                
                # Парсим файл
                participants = participants_service.parse_participants_file(temp_file_path)
                
                # Удаляем временный файл
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                
                # Валидируем
                is_valid, error_message = participants_service.validate_participants(participants)
                
                if not is_valid:
                    await message.answer(
                        f"❌ **Ошибка валидации:**\n{error_message}\n\n"
                        f"Попробуйте еще раз.",
                        parse_mode="Markdown"
                    )
                    return
                
                # Сохраняем в состояние
                await state.update_data(participants_list=participants)
                await state.set_state(ParticipantsInput.confirm_participants)
                
                # Показываем для подтверждения
                display_text = participants_service.format_participants_for_display(participants)
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_participants"),
                        InlineKeyboardButton(text="💾 Сохранить и использовать", callback_data="save_and_confirm_participants")
                    ],
                    [
                        InlineKeyboardButton(text="⬅️ Назад", callback_data="upload_participants_file"),
                        InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")
                    ]
                ])
                
                await message.answer(
                    f"{display_text}\n\n**Все верно?**",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                
            except FileError as e:
                await message.answer(f"❌ Ошибка при обработке файла: {e}")
            finally:
                # Убеждаемся что файл удален
                if os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except:
                        pass
            
        except Exception as e:
            logger.error(f"Ошибка при обработке файла участников: {e}")
            await message.answer(
                "❌ Произошла ошибка при обработке файла. Попробуйте еще раз."
            )
    
    @router.callback_query(F.data == "confirm_meeting_info")
    async def confirm_meeting_info(callback: CallbackQuery, state: FSMContext):
        """Подтверждение автоматически извлеченной информации о встрече"""
        try:
            # Получаем количество участников для сообщения
            data = await state.get_data()
            participants = data.get('participants_list', [])
            participants_count = len(participants)

            await callback.answer("✅ Информация о встрече подтверждена")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            await callback.message.answer(
                f"✅ Список участников сохранен ({participants_count} чел.)\n\n"
                f"📝 Теперь выберите способ создания протокола:"
            )

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state)

        except Exception as e:
            logger.error(f"Ошибка при подтверждении информации о встрече: {e}")
            await callback.message.answer("❌ Произошла ошибка.")

    @router.callback_query(F.data == "save_meeting_info")
    async def save_meeting_info(callback: CallbackQuery, state: FSMContext):
        """Сохранение и подтверждение автоматически извлеченной информации"""
        try:
            data = await state.get_data()
            meeting_info_data = data.get('meeting_info', {})

            if not meeting_info_data:
                await callback.answer("❌ Информация о встрече не найдена", show_alert=True)
                return

            # Сохраняем список участников для пользователя
            participants = data.get('participants_list', [])
            participants_count = len(participants)
            
            if participants:
                participants_json = participants_service.participants_to_json([
                    {"name": p["name"], "role": p.get("role", "")}
                    for p in participants
                ])

                # Обновляем пользователя в БД
                from database import db
                await db.update_user_saved_participants(callback.from_user.id, participants_json)

            await callback.answer("✅ Информация сохранена и будет использована")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            await callback.message.answer(
                f"✅ Список участников сохранен ({participants_count} чел.) и добавлен в избранное\n\n"
                f"📝 Теперь выберите способ создания протокола:"
            )

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state)

        except Exception as e:
            logger.error(f"Ошибка при сохранении информации о встрече: {e}")
            await callback.message.answer("❌ Произошла ошибка при сохранении.")

    @router.callback_query(F.data == "confirm_participants")
    async def confirm_participants(callback: CallbackQuery, state: FSMContext):
        """Подтверждение списка участников"""
        try:
            # Получаем количество участников для сообщения
            data = await state.get_data()
            participants = data.get('participants_list', [])
            participants_count = len(participants)

            await callback.answer("✅ Список участников подтвержден")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            await callback.message.answer(
                f"✅ Список участников сохранен ({participants_count} чел.)\n\n"
                f"📝 Теперь выберите способ создания протокола:"
            )

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state)

        except Exception as e:
            logger.error(f"Ошибка при подтверждении участников: {e}")
            await callback.message.answer("❌ Произошла ошибка.")
    
    @router.callback_query(F.data == "save_and_confirm_participants")
    async def save_and_confirm_participants(callback: CallbackQuery, state: FSMContext):
        """Сохранение и подтверждение списка участников"""
        try:
            data = await state.get_data()
            participants = data.get('participants_list', [])
            participants_count = len(participants)

            if not participants:
                await callback.answer("❌ Список участников пуст", show_alert=True)
                return

            # Сохраняем список для пользователя
            participants_json = participants_service.participants_to_json(participants)

            # Обновляем пользователя в БД
            from database import db
            await db.update_user_saved_participants(callback.from_user.id, participants_json)

            await callback.answer("✅ Список сохранен и будет использован")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            await callback.message.answer(
                f"✅ Список участников сохранен ({participants_count} чел.) и добавлен в избранное\n\n"
                f"📝 Теперь выберите способ создания протокола:"
            )

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state)

        except Exception as e:
            logger.error(f"Ошибка при сохранении участников: {e}")
            await callback.message.answer("❌ Произошла ошибка при сохранении.")
    
    @router.callback_query(F.data == "cancel_participants")
    async def cancel_participants(callback: CallbackQuery, state: FSMContext):
        """Отмена ввода участников"""
        try:
            await callback.answer("Ввод отменен")
            await state.clear()
            await callback.message.answer("❌ Ввод участников отменен.")
            
        except Exception as e:
            logger.error(f"Ошибка при отмене: {e}")
    
    return router


