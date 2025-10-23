"""
Обработчики команд
"""

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from loguru import logger

from services.user_service import UserService
from services.template_service import TemplateService
from services.enhanced_llm_service import EnhancedLLMService
from src.models.user import UserCreate


def setup_command_handlers(user_service: UserService, template_service: TemplateService, 
                          llm_service: EnhancedLLMService) -> Router:
    """Настройка обработчиков команд"""
    router = Router()
    
    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext):
        """Обработчик команды /start"""
        try:
            # Создаем или получаем пользователя
            user = await user_service.get_or_create_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            
            from ux.message_builder import MessageBuilder
            from ux.quick_actions import QuickActionsUI
            
            welcome_text = MessageBuilder.welcome_message()
            main_menu = QuickActionsUI.create_main_menu(message.from_user.id)
            
            await message.answer(
                welcome_text,
                reply_markup=main_menu,
                parse_mode="Markdown"
            )
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка в start_handler: {e}")
            await message.answer("❌ Произошла ошибка при запуске. Попробуйте еще раз.")
    
    @router.message(Command("help"))
    async def help_handler(message: Message):
        """Обработчик команды /help"""
        from ux.message_builder import MessageBuilder
        help_text = MessageBuilder.help_message()
        await message.answer(help_text, parse_mode="Markdown")
    
    @router.message(Command("settings"))
    async def settings_handler(message: Message):
        """Обработчик команды /settings"""
        try:
            user = await user_service.get_user_by_telegram_id(message.from_user.id)
            available_providers = llm_service.get_available_providers()
            
            if not available_providers:
                await message.answer(
                    "❌ Нет доступных LLM провайдеров. "
                    "Проверьте конфигурацию API ключей."
                )
                return
            
            current_llm = user.preferred_llm if user else 'openai'
            # Готовим информацию о выбранной модели OpenAI (если применимо)
            from config import settings as app_settings
            openai_model_name = None
            try:
                if current_llm == 'openai' and getattr(app_settings, 'openai_models', None):
                    selected_key = getattr(user, 'preferred_openai_model_key', None) if user else None
                    # Выбираем текущий пресет: выбранный пользователем или дефолтный первый
                    preset = None
                    if selected_key:
                        preset = next((p for p in app_settings.openai_models if p.key == selected_key), None)
                    if not preset and len(app_settings.openai_models) > 0:
                        preset = app_settings.openai_models[0]
                    if preset:
                        openai_model_name = preset.name
            except Exception:
                openai_model_name = None
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'✅ ' if provider_key == current_llm else ''}{provider_name}",
                    callback_data=f"set_llm_{provider_key}"
                )]
                for provider_key, provider_name in available_providers.items()
            ] + [
                [InlineKeyboardButton(
                    text="🔄 Сбросить предпочтения (спрашивать каждый раз)",
                    callback_data="reset_llm_preference"
                )]
            ])
            
            # Определяем статус автоматического выбора
            auto_select_status = "включён" if user and user.preferred_llm is not None else "выключен"
            
            base_text = (
                f"⚙️ **Настройки бота**\n\n"
                f"Текущий LLM: {available_providers.get(current_llm, 'Не настроен')}\n"
                f"Автоматический выбор: {auto_select_status}\n"
            )
            if openai_model_name:
                base_text += f"Модель OpenAI: {openai_model_name}\n\n"
            else:
                base_text += "\n"
            base_text += "Выберите LLM провайдера:"

            await message.answer(
                base_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в settings_handler: {e}")
            await message.answer("❌ Произошла ошибка при загрузке настроек.")
    
    @router.message(Command("templates"))
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
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await message.answer(
                f"📝 **Доступные шаблоны:** {len(templates)}\n\n"
                "Выберите категорию для просмотра:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в templates_handler: {e}")
            await message.answer("❌ Произошла ошибка при загрузке шаблонов.")
    
    @router.message(Command("feedback"))
    async def feedback_handler(message: Message):
        """Обработчик команды /feedback"""
        from ux.feedback_system import FeedbackUI
        
        keyboard = FeedbackUI.create_feedback_type_keyboard()
        await message.answer(
            "💬 **Обратная связь**\n\n"
            "Помогите нам улучшить бота! Выберите тип обратной связи:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    return router
