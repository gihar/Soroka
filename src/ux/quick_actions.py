"""
Система быстрых действий и улучшенного пользовательского интерфейса
"""

from typing import Optional

from aiogram import F, Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from loguru import logger

from src.config import settings
from src.services import TemplateService
from src.utils.telegram_safe import safe_answer
from src.utils.template_sort import sort_templates_by_name


class QuickActionsUI:
    """Интерфейс быстрых действий"""
    
    @staticmethod
    def create_main_menu(user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
        """Создать главное меню с быстрыми действиями"""
        from src.utils.admin_utils import is_admin
        
        keyboard = [
            [
                KeyboardButton(text="📝 Мои шаблоны"),
                KeyboardButton(text="⚙️ Настройки")
            ],
            [
                KeyboardButton(text="❓ Помощь"),
                KeyboardButton(text="💬 Обратная связь")
            ]
        ]
        
        # Добавляем кнопку администратора только для админов
        if user_id and is_admin(user_id):
            keyboard.append([
                KeyboardButton(text="🔧 Меню администратора")
            ])
        
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите действие или отправьте файл..."
        )
    
    @staticmethod
    def create_record_actions_menu() -> tuple[str, InlineKeyboardMarkup]:
        """Меню действий с записью: единый текст и клавиатура.

        Единая точка правды для обеих точек приёма записи — файла
        (media_handler) и ссылки (_process_url). Возвращает текст «Файл
        получен» и клавиатуру с кнопками быстрой обработки и настройки.
        """
        text = (
            "📎 **Файл получен**\n\n"
            "🚀 **Быстрая обработка** — умный шаблон + сохранённые настройки\n"
            "⚙️ **Настроить** — выбрать участников, шаблон, ИИ"
        )
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
        return text, keyboard

    @staticmethod
    def create_settings_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
        """Меню настроек. Админ дополнительно видит выбор активной модели ИИ."""
        buttons = []

        if is_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="🤖 Модель ИИ",
                    callback_data="settings_active_model",
                )
            ])

        buttons.extend([
            [
                InlineKeyboardButton(
                    text="📤 Вывод протокола",
                    callback_data="settings_protocol_output",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Шаблон по умолчанию",
                    callback_data="settings_default_template",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="settings_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить настройки",
                    callback_data="settings_reset",
                )
            ],
        ])

        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def create_admin_menu() -> InlineKeyboardMarkup:
        """Меню администратора"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="📊 Статистика системы",
                    callback_data="admin_status"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏥 Проверка здоровья",
                    callback_data="admin_health"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📈 Производительность",
                    callback_data="admin_performance"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧹 Управление файлами",
                    callback_data="admin_cleanup"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎙️ Режим транскрипции",
                    callback_data="admin_transcription"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сброс компонентов",
                    callback_data="admin_reset"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Экспорт статистики",
                    callback_data="admin_export"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Справка",
                    callback_data="admin_help"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Вернуться в главное меню",
                    callback_data="admin_back_to_main"
                )
            ]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)


def setup_quick_actions_handlers() -> Router:
    """Настройка обработчиков быстрых действий"""
    router = Router()
    
    @router.message(F.text == "📤 Загрузить файл")
    async def upload_file_button_handler(message: Message):
        """Обработчик кнопки загрузки файла"""
        max_mb = settings.telegram_max_file_size // (1024 * 1024)
        await message.answer(
            "📤 **Загрузка файла**\n\n"
            "Отправьте аудио или видео файл, либо ссылку на файл любым способом:\n"
            "• 🎵 Как аудио сообщение\n"
            "• 🎬 Как видео сообщение\n"
            "• 📎 Как документ\n"
            "• 🎤 Голосовое сообщение\n\n"
            f"💡 Максимальный размер: {max_mb}MB.\n"
            "Если файл превышает максимальный размер, отправьте, пожалуйста, ссылку на него (например, Google Drive или Яндекс.Диск) с доступом на скачивание."
        )
    
    @router.message(F.text == "📝 Мои шаблоны")
    async def my_templates_button_handler(message: Message):
        """Обработчик кнопки шаблонов"""
        try:
            template_service = TemplateService()
            templates = await template_service.get_all_templates()
            
            if not templates:
                await message.answer("📝 Шаблоны не найдены.")
                return
            
            templates = sort_templates_by_name(templates)

            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=t.name,
                    callback_data=f"view_template_{t.id}"
                )] for t in templates
            ]

            # Добавляем кнопку создания шаблона
            keyboard_buttons.append([InlineKeyboardButton(
                text="➕ Добавить шаблон",
                callback_data="add_template"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_answer(message, 
                f"📝 **Доступные шаблоны ({len(templates)}):**",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в my_templates_button_handler: {e}")
            await message.answer("❌ Произошла ошибка при загрузке шаблонов.")
    
    @router.message(F.text == "⚙️ Настройки")
    async def settings_button_handler(message: Message):
        """Обработчик кнопки настроек"""
        from src.utils.admin_utils import is_admin as _is_admin
        keyboard = QuickActionsUI.create_settings_menu(
            is_admin=_is_admin(message.from_user.id)
        )
        await message.answer(
            "⚙️ **Настройки бота**\n\n"
            "Настройте бота под ваши предпочтения:",
            reply_markup=keyboard
        )
    
    @router.message(F.text == "📊 Статистика")
    async def stats_button_handler(message: Message):
        """Обработчик кнопки статистики"""
        logger.info(f"Пользователь {message.from_user.id} запросил статистику")
        try:
            from datetime import datetime

            from reliability.middleware import monitoring_middleware
            from src.database import history_repo
            
            # Получаем статистику пользователя из базы данных
            user_stats = await history_repo.get_user_stats(message.from_user.id)
            
            # Получаем системную статистику
            system_stats = monitoring_middleware.get_stats()
            
            if user_stats:
                # Форматируем личную статистику
                total_files = user_stats.get('total_files', 0)
                active_days = user_stats.get('active_days', 0)
                favorite_templates = user_stats.get('favorite_templates', [])
                llm_providers = user_stats.get('llm_providers', [])
                
                # Строим сообщение
                stats_text = "📊 **Ваша статистика**\n\n"
                stats_text += f"🔄 **Обработано файлов:** {total_files}\n"
                stats_text += f"📅 **Активных дней:** {active_days}\n"
                
                if user_stats.get('first_file_date'):
                    try:
                        first_date = datetime.fromisoformat(user_stats['first_file_date'].replace('Z', '+00:00'))
                        days_since_first = (datetime.now() - first_date.replace(tzinfo=None)).days
                        stats_text += f"🎯 **Дней с начала использования:** {days_since_first}\n"
                    except:
                        pass
                
                # Любимые шаблоны
                if favorite_templates:
                    stats_text += "\n📝 **Популярные шаблоны:**\n"
                    for template in favorite_templates[:3]:
                        stats_text += f"• {template['name']}: {template['count']} раз\n"
                
                # LLM провайдеры
                if llm_providers:
                    stats_text += "\n🤖 **Используемые AI модели:**\n"
                    for provider in llm_providers[:3]:
                        provider_name = provider['llm_provider'].title() if provider['llm_provider'] else 'Неизвестно'
                        stats_text += f"• {provider_name}: {provider['count']} раз\n"
                
                # System stats only for admins
                from src.utils.admin_utils import is_admin
                if is_admin(message.from_user.id):
                    stats_text += "\n🌐 **Общая статистика системы:**\n"
                    stats_text += f"• Всего запросов: {system_stats.get('total_requests', 0)}\n"
                    stats_text += f"• Активных пользователей: {system_stats.get('active_users', 0)}\n"
                    stats_text += f"• Среднее время ответа: {system_stats.get('average_processing_time', 0):.2f}с\n"
                    if system_stats.get('error_rate', 0) > 0:
                        stats_text += f"• Процент ошибок: {system_stats.get('error_rate', 0):.1f}%\n"
                    else:
                        stats_text += "• ✅ Система работает стабильно\n"

            else:
                stats_text = (
                    "📊 **Статистика**\n\n"
                    "🔄 **Обработано файлов:** 0\n"
                    "🚀 Отправьте свой первый файл для обработки!"
                )
            
            await safe_answer(message, stats_text, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            await safe_answer(message, 
                "📊 **Статистика**\n\n"
                "❌ Временно недоступна статистика.\n"
                "Попробуйте позже или обратитесь к администратору.",
                parse_mode="Markdown"
            )
    
    @router.message(F.text == "❓ Помощь")
    async def help_button_handler(message: Message):
        """Обработчик кнопки помощи"""
        from ux.message_builder import MessageBuilder
        help_text = MessageBuilder.help_message()
        await safe_answer(message, help_text, parse_mode="Markdown")
    
    @router.message(F.text == "💬 Обратная связь")
    async def feedback_button_handler(message: Message):
        """Обработчик кнопки обратной связи"""
        from ux.feedback_system import FeedbackUI
        keyboard = FeedbackUI.create_feedback_type_keyboard()
        await safe_answer(message, 
            "💬 **Обратная связь**\n\n"
            "Помогите нам стать лучше! Выберите тип обратной связи:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    @router.message(F.text == "🔧 Меню администратора")
    async def admin_menu_button_handler(message: Message):
        """Обработчик кнопки меню администратора"""
        from src.utils.admin_utils import is_admin
        
        # Проверяем права администратора
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        # Показываем меню администратора
        keyboard = QuickActionsUI.create_admin_menu()
        await safe_answer(message, 
            "🔧 **Меню администратора**\n\n"
            "Выберите действие:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    return router
