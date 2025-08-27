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
from models.user import UserCreate


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
            main_menu = QuickActionsUI.create_main_menu()
            
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
            
            await message.answer(
                f"⚙️ **Настройки бота**\n\n"
                f"Текущий LLM: {available_providers.get(current_llm, 'Не настроен')}\n"
                f"Автоматический выбор: {auto_select_status}\n\n"
                f"Выберите LLM провайдера:",
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
            
            await message.answer(
                "📝 **Доступные шаблоны:**",
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
