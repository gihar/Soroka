"""
Система быстрых действий и улучшенного пользовательского интерфейса
"""

from typing import Dict, List, Any, Optional
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, 
    InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from loguru import logger


class QuickActionsUI:
    """Интерфейс быстрых действий"""
    
    @staticmethod
    def create_main_menu() -> ReplyKeyboardMarkup:
        """Создать главное меню с быстрыми действиями"""
        keyboard = [
            [
                KeyboardButton(text="📤 Загрузить файл"),
                KeyboardButton(text="📝 Мои шаблоны")
            ],
            [
                KeyboardButton(text="⚙️ Настройки"),
                KeyboardButton(text="📊 Статистика")
            ],
            [
                KeyboardButton(text="❓ Помощь"),
                KeyboardButton(text="💬 Обратная связь")
            ]
        ]
        
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True,
            one_time_keyboard=False,
            input_field_placeholder="Выберите действие или отправьте файл..."
        )
    
    @staticmethod
    def create_file_actions_menu() -> InlineKeyboardMarkup:
        """Меню действий с файлом"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="🚀 Быстрая обработка",
                    callback_data="quick_process_default"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎨 Выбрать шаблон",
                    callback_data="select_template"
                ),
                InlineKeyboardButton(
                    text="🤖 Выбрать ИИ",
                    callback_data="select_llm"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Настроить обработку",
                    callback_data="configure_processing"
                )
            ]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def create_template_quick_menu() -> InlineKeyboardMarkup:
        """Быстрое меню шаблонов"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="📋 Стандартный протокол",
                    callback_data="quick_template_standard"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💼 Деловая встреча",
                    callback_data="quick_template_business"
                ),
                InlineKeyboardButton(
                    text="🎓 Учебное занятие",
                    callback_data="quick_template_education"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔬 Исследование",
                    callback_data="quick_template_research"
                ),
                InlineKeyboardButton(
                    text="🎯 Планирование",
                    callback_data="quick_template_planning"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Все шаблоны",
                    callback_data="view_all_templates"
                ),
                InlineKeyboardButton(
                    text="➕ Создать новый",
                    callback_data="create_template"
                )
            ]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def create_settings_menu() -> InlineKeyboardMarkup:
        """Меню настроек"""
        buttons = [
            [
                InlineKeyboardButton(
                    text="🤖 Предпочитаемый ИИ",
                    callback_data="settings_preferred_llm"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Диаризация",
                    callback_data="settings_diarization"
                ),
                InlineKeyboardButton(
                    text="🎵 Качество аудио",
                    callback_data="settings_audio_quality"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Шаблон по умолчанию",
                    callback_data="settings_default_template"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить настройки",
                    callback_data="settings_reset"
                )
            ]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)


class CommandShortcuts:
    """Система сокращенных команд"""
    
    # Алиасы команд
    COMMAND_ALIASES = {
        "t": "templates",      # /t -> /templates
        "s": "settings",       # /s -> /settings
        "h": "help",          # /h -> /help
        "st": "status",       # /st -> /status
        "fb": "feedback",     # /fb -> /feedback
        "q": "quick"          # /q -> /quick
    }
    
    @staticmethod
    def get_command_help() -> str:
        """Получить справку по быстрым командам"""
        return (
            "⚡ **Быстрые команды**\n\n"
            "🔤 **Сокращения:**\n"
            "• `/t` → `/templates` - шаблоны\n"
            "• `/s` → `/settings` - настройки\n"
            "• `/h` → `/help` - помощь\n"
            "• `/st` → `/status` - статус системы\n"
            "• `/fb` → `/feedback` - обратная связь\n"
            "• `/q` → `/quick` - быстрые действия\n\n"
            
            "⚡ **Быстрые действия:**\n"
            "• Отправьте файл + нажмите \"🚀 Быстрая обработка\"\n"
            "• Используйте главное меню для навигации\n"
            "• Команда `/quick` для панели быстрых действий\n\n"
            
            "🎯 **Профили обработки:**\n"
            "• `/quick meeting` - быстрая обработка встречи\n"
            "• `/quick lecture` - обработка лекции\n"
            "• `/quick interview` - обработка интервью\n\n"
            
            "💡 **Подсказка:** используйте кнопки меню вместо команд!"
        )


def setup_quick_actions_handlers() -> Router:
    """Настройка обработчиков быстрых действий"""
    router = Router()
    
    @router.message(Command("quick"))
    async def quick_command_handler(message: Message):
        """Обработчик команды /quick"""
        # Проверяем, есть ли аргументы
        command_parts = message.text.split()
        
        if len(command_parts) > 1:
            action = command_parts[1].lower()
            
            # Быстрые профили обработки
            if action == "meeting":
                await message.answer(
                    "🏢 **Профиль: Деловая встреча**\n\n"
                    "Отправьте аудио или видео файл встречи.\n"
                    "Будет использован шаблон для деловых встреч с автоматическим определением участников.",
                    reply_markup=QuickActionsUI.create_main_menu()
                )
            elif action == "lecture":
                await message.answer(
                    "🎓 **Профиль: Лекция/Семинар**\n\n"
                    "Отправьте запись учебного занятия.\n"
                    "Будет создан конспект с выделением ключевых моментов.",
                    reply_markup=QuickActionsUI.create_main_menu()
                )
            elif action == "interview":
                await message.answer(
                    "🎤 **Профиль: Интервью**\n\n"
                    "Отправьте запись интервью.\n"
                    "Будет создана транскрипция с указанием ролей участников.",
                    reply_markup=QuickActionsUI.create_main_menu()
                )
            else:
                await message.answer(
                    f"❓ Неизвестный профиль: {action}\n\n"
                    f"Доступные профили: meeting, lecture, interview"
                )
        else:
            # Показываем панель быстрых действий
            keyboard = QuickActionsUI.create_file_actions_menu()
            await message.answer(
                "⚡ **Панель быстрых действий**\n\n"
                "Выберите действие или отправьте файл для обработки:",
                reply_markup=keyboard
            )
    
    @router.message(F.text == "📤 Загрузить файл")
    async def upload_file_button_handler(message: Message):
        """Обработчик кнопки загрузки файла"""
        await message.answer(
            "📤 **Загрузка файла**\n\n"
            "Отправьте аудио или видео файл любым способом:\n"
            "• 🎵 Как аудио сообщение\n"
            "• 🎬 Как видео сообщение\n"
            "• 📎 Как документ\n"
            "• 🎤 Голосовое сообщение\n\n"
            "💡 Максимальный размер: 20MB"
        )
    
    @router.message(F.text == "📝 Мои шаблоны")
    async def my_templates_button_handler(message: Message):
        """Обработчик кнопки шаблонов"""
        keyboard = QuickActionsUI.create_template_quick_menu()
        await message.answer(
            "📝 **Управление шаблонами**\n\n"
            "Выберите готовый шаблон или создайте собственный:",
            reply_markup=keyboard
        )
    
    @router.message(F.text == "⚙️ Настройки")
    async def settings_button_handler(message: Message):
        """Обработчик кнопки настроек"""
        keyboard = QuickActionsUI.create_settings_menu()
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
            from database import db
            from reliability.middleware import monitoring_middleware
            from reliability.health_check import health_checker
            from datetime import datetime, timedelta
            
            # Получаем статистику пользователя из базы данных
            user_stats = await db.get_user_stats(message.from_user.id)
            
            # Получаем системную статистику
            system_stats = monitoring_middleware.get_stats()
            
            if user_stats:
                # Форматируем личную статистику
                total_files = user_stats.get('total_files', 0)
                active_days = user_stats.get('active_days', 0)
                favorite_templates = user_stats.get('favorite_templates', [])
                llm_providers = user_stats.get('llm_providers', [])
                
                # Строим сообщение
                stats_text = f"📊 **Ваша статистика**\n\n"
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
                    stats_text += f"\n📝 **Популярные шаблоны:**\n"
                    for template in favorite_templates[:3]:
                        stats_text += f"• {template['name']}: {template['count']} раз\n"
                
                # LLM провайдеры
                if llm_providers:
                    stats_text += f"\n🤖 **Используемые AI модели:**\n"
                    for provider in llm_providers[:3]:
                        provider_name = provider['llm_provider'].title() if provider['llm_provider'] else 'Неизвестно'
                        stats_text += f"• {provider_name}: {provider['count']} раз\n"
                
                # Системная статистика
                stats_text += f"\n🌐 **Общая статистика системы:**\n"
                stats_text += f"• Всего запросов: {system_stats.get('total_requests', 0)}\n"
                stats_text += f"• Активных пользователей: {system_stats.get('active_users', 0)}\n"
                stats_text += f"• Среднее время ответа: {system_stats.get('average_processing_time', 0):.2f}с\n"
                
                if system_stats.get('error_rate', 0) > 0:
                    stats_text += f"• Процент ошибок: {system_stats.get('error_rate', 0):.1f}%\n"
                else:
                    stats_text += f"• ✅ Система работает стабильно\n"
                
            else:
                # Новый пользователь
                stats_text = f"📊 **Добро пожаловать!**\n\n"
                stats_text += f"🔄 **Обработано файлов:** 0\n"
                stats_text += f"📅 **Активных дней:** 0\n\n"
                stats_text += f"🚀 Отправьте свой первый файл для обработки!\n\n"
                
                # Системная статистика для новых пользователей
                stats_text += f"🌐 **Статистика системы:**\n"
                stats_text += f"• Всего запросов: {system_stats.get('total_requests', 0)}\n"
                stats_text += f"• Активных пользователей: {system_stats.get('active_users', 0)}\n"
                stats_text += f"• Среднее время ответа: {system_stats.get('average_processing_time', 0):.2f}с\n"
            
            await message.answer(stats_text, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            await message.answer(
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
        await message.answer(help_text, parse_mode="Markdown")
    
    @router.message(F.text == "💬 Обратная связь")
    async def feedback_button_handler(message: Message):
        """Обработчик кнопки обратной связи"""
        from ux.feedback_system import FeedbackUI
        keyboard = FeedbackUI.create_feedback_type_keyboard()
        await message.answer(
            "💬 **Обратная связь**\n\n"
            "Помогите нам стать лучше! Выберите тип обратной связи:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    # Обработчики быстрых действий с файлами
    @router.callback_query(F.data == "quick_process_default")
    async def quick_process_default_handler(callback: CallbackQuery):
        """Быстрая обработка с настройками по умолчанию"""
        await callback.message.edit_text(
            "🚀 **Быстрая обработка**\n\n"
            "Будут использованы настройки по умолчанию:\n"
            "• 📝 Стандартный шаблон протокола\n"
            "• 🤖 Автоматический выбор ИИ\n"
            "• 👥 Диаризация включена\n\n"
            "⏳ Начинаю обработку..."
        )
        # Здесь будет вызов обработки с настройками по умолчанию
    
    @router.callback_query(F.data.startswith("quick_template_"))
    async def quick_template_handler(callback: CallbackQuery):
        """Обработчик быстрого выбора шаблона"""
        template_type = callback.data.split("_")[-1]
        
        template_names = {
            "standard": "Стандартный протокол встречи",
            "business": "Деловая встреча",
            "education": "Учебное занятие",
            "research": "Исследовательская работа",
            "planning": "Планирование проекта"
        }
        
        template_name = template_names.get(template_type, "Выбранный шаблон")
        
        await callback.message.edit_text(
            f"📝 **Выбран шаблон:** {template_name}\n\n"
            f"Теперь отправьте файл для обработки или выберите ИИ для генерации."
        )
    
    # Команды-алиасы
    for alias, original in CommandShortcuts.COMMAND_ALIASES.items():
        @router.message(Command(alias))
        async def alias_handler(message: Message, command=original):
            """Обработчик команд-алиасов"""
            await message.answer(
                f"↪️ Выполняю команду `/{command}`",
                parse_mode="Markdown"
            )
            # Здесь должен быть вызов соответствующего обработчика
    
    return router


class UserGuidance:
    """Система подсказок и руководства пользователя"""
    
    @staticmethod
    def get_contextual_help(context: str) -> str:
        """Получить контекстную помощь"""
        help_texts = {
            "file_upload": (
                "📤 **Как загрузить файл:**\n\n"
                "1. Нажмите на скрепку 📎 в Telegram\n"
                "2. Выберите \"Файл\" или \"Медиа\"\n"
                "3. Найдите ваш аудио/видео файл\n"
                "4. Отправьте файл боту\n\n"
                "💡 Можно также:\n"
                "• Записать голосовое сообщение 🎤\n"
                "• Записать видео-сообщение 📹\n"
                "• Переслать файл из другого чата"
            ),
            "template_creation": (
                "📝 **Создание шаблона:**\n\n"
                "1. Нажмите \"➕ Добавить шаблон\"\n"
                "2. Введите название (например: \"Планерка\")\n"
                "3. Добавьте описание\n"
                "4. Создайте содержимое с переменными\n"
                "5. Используйте предпросмотр\n"
                "6. Сохраните шаблон\n\n"
                "🔧 **Переменные:**\n"
                "• {{participants}} - участники\n"
                "• {{agenda}} - повестка\n"
                "• {{decisions}} - решения"
            ),
            "troubleshooting": (
                "🔧 **Решение проблем:**\n\n"
                "❌ **Файл не обрабатывается:**\n"
                "• Проверьте размер (макс. 20MB)\n"
                "• Убедитесь в поддержке формата\n"
                "• Попробуйте отправить как документ\n\n"
                "🐌 **Медленная обработка:**\n"
                "• Большие файлы обрабатываются дольше\n"
                "• Проверьте интернет-соединение\n"
                "• Попробуйте в другое время\n\n"
                "🤖 **Плохое качество протокола:**\n"
                "• Используйте файлы с четкой речью\n"
                "• Выберите подходящий шаблон\n"
                "• Попробуйте другой ИИ-провайдер"
            )
        }
        
        return help_texts.get(context, "❓ Контекстная справка недоступна")
    
    @staticmethod
    def get_onboarding_steps() -> List[str]:
        """Получить шаги онбординга для новых пользователей"""
        return [
            "👋 Добро пожаловать! Это бот для создания протоколов встреч",
            "📤 Первый шаг: отправьте аудио или видео файл встречи",
            "📝 Второй шаг: выберите шаблон протокола из списка",
            "🤖 Третий шаг: выберите ИИ или оставьте автовыбор",
            "⏳ Дождитесь обработки - это займет несколько минут",
            "📋 Получите готовый протокол в удобном формате!",
            "💡 Совет: создайте собственные шаблоны в разделе /templates"
        ]
