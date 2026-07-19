"""
Обработчики команд
"""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from services.template_service import TemplateService
from services.user_service import UserService
from src.utils.telegram_safe import safe_answer


def setup_command_handlers(user_service: UserService, template_service: TemplateService, 
) -> Router:
    """Настройка обработчиков команд"""
    router = Router()
    
    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext):
        """Обработчик команды /start"""
        try:
            # Создаем или получаем пользователя
            await user_service.get_or_create_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            
            from ux.message_builder import MessageBuilder
            from ux.quick_actions import QuickActionsUI
            
            welcome_text = MessageBuilder.welcome_message()
            main_menu = QuickActionsUI.create_main_menu(message.from_user.id)
            
            await safe_answer(message, 
                welcome_text,
                reply_markup=main_menu,
                parse_mode="Markdown"
            )
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка в start_handler: {e}")
            await message.answer("❌ Произошла ошибка при запуске. Попробуйте еще раз.")
    
    @router.message(Command("help", "h"))
    async def help_handler(message: Message):
        """Обработчик команды /help"""
        from ux.message_builder import MessageBuilder
        help_text = MessageBuilder.help_message()
        await safe_answer(message, help_text, parse_mode="Markdown")
    
    @router.message(Command("settings", "s"))
    async def settings_handler(message: Message):
        """Обработчик команды /settings."""
        try:
            from src.utils.admin_utils import is_admin as _is_admin
            from src.ux.quick_actions import QuickActionsUI

            is_admin_user = _is_admin(message.from_user.id)
            keyboard = QuickActionsUI.create_settings_menu(is_admin=is_admin_user)

            text = "⚙️ **Настройки бота**\n\n"

            if is_admin_user:
                # Admins see the currently active model name (read-only line)
                try:
                    from src.database import app_settings_repo, model_preset_repo

                    active_key = await app_settings_repo.get_active_model_key()
                    if active_key:
                        preset = await model_preset_repo.get_by_key(active_key)
                        if preset:
                            text += f"Активная модель: {preset['name']}\n\n"
                        else:
                            text += "⚠️ Активная модель не найдена\n\n"
                    else:
                        text += "⚠️ Активная модель не настроена\n\n"
                except Exception as e:
                    logger.warning(f"Не удалось загрузить активную модель: {e}")

            text += "Настройте бота под ваши предпочтения:"

            await safe_answer(message, text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в settings_handler: {e}")
            await message.answer("❌ Произошла ошибка при загрузке настроек.")
    
    @router.message(Command("templates", "t"))
    async def templates_handler(message: Message):
        """Обработчик команды /templates"""
        try:
            templates = await template_service.get_all_templates()
            
            if not templates:
                await message.answer("📝 Шаблоны не найдены.")
                return
            
            # Группируем шаблоны по категориям
            from collections import defaultdict
            categories = defaultdict(list)
            for template in templates:
                category = template.category or 'general'
                categories[category].append(template)
            
            # Создаем клавиатуру с категориями
            category_names = {
                'management': '👔 Управленческие',
                'product': '🚀 Продуктовые',
                'technical': '⚙️ Технические',
                'general': '📋 Общие',
                'sales': '💼 Продажи'
            }
            
            keyboard_buttons = []
            
            # Добавляем категории
            for category, cat_templates in sorted(categories.items()):
                category_name = category_names.get(category, f'📁 {category.title()}')
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{category_name} ({len(cat_templates)})",
                    callback_data=f"view_template_category_{category}"
                )])
            
            # Добавляем кнопку "Все шаблоны"
            keyboard_buttons.append([InlineKeyboardButton(
                text="📝 Все шаблоны",
                callback_data="view_template_category_all"
            )])
            
            # Добавляем кнопку создания шаблона
            keyboard_buttons.append([InlineKeyboardButton(
                text="➕ Добавить шаблон",
                callback_data="add_template"
            )])

            # Справка: как устроены шаблоны (переменные, {% if %}, пример)
            keyboard_buttons.append([InlineKeyboardButton(
                text="ℹ️ Как устроены шаблоны",
                callback_data="templates_help"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await safe_answer(message, 
                f"📝 **Доступные шаблоны:** {len(templates)}\n\n"
                "Выберите категорию для просмотра:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в templates_handler: {e}")
            await message.answer("❌ Произошла ошибка при загрузке шаблонов.")
    
    @router.message(Command("feedback", "fb"))
    async def feedback_handler(message: Message):
        """Обработчик команды /feedback"""
        from ux.feedback_system import FeedbackUI
        
        keyboard = FeedbackUI.create_feedback_type_keyboard()
        await safe_answer(message, 
            "💬 **Обратная связь**\n\n"
            "Помогите нам улучшить бота! Выберите тип обратной связи:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    return router
