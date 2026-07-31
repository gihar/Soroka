"""
Обработчики команд
"""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from src.services.template_service import TemplateService
from src.services.user_service import UserService
from src.utils.telegram_safe import safe_answer
from src.utils.template_sort import category_label
from src.ux.html_text import esc


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
            
            from src.ux.message_builder import MessageBuilder
            from src.ux.quick_actions import QuickActionsUI
            
            welcome_text = MessageBuilder.welcome_message()
            main_menu = QuickActionsUI.create_main_menu(message.from_user.id)
            
            await safe_answer(message,
                welcome_text,
                reply_markup=main_menu,
                parse_mode="HTML"
            )
            await state.clear()
            
        except Exception as e:
            logger.error(f"Ошибка в start_handler: {e}")
            await message.answer(
                "❌ Не получилось запустить бота.\n"
                "Попробуйте ещё раз командой /start."
            )
    
    @router.message(Command("help", "h"))
    async def help_handler(message: Message):
        """Обработчик команды /help"""
        from src.ux.message_builder import MessageBuilder
        help_text = MessageBuilder.help_message()
        await safe_answer(message, help_text, parse_mode="HTML")
    
    @router.message(Command("settings", "s"))
    async def settings_handler(message: Message):
        """Обработчик команды /settings."""
        try:
            from src.utils.admin_utils import is_admin as _is_admin
            from src.ux.quick_actions import QuickActionsUI

            is_admin_user = _is_admin(message.from_user.id)
            keyboard = QuickActionsUI.create_settings_menu(is_admin=is_admin_user)

            text = "⚙️ <b>Настройки бота</b>\n\n"

            if is_admin_user:
                # Admins see the currently active model name (read-only line)
                try:
                    from src.database import app_settings_repo, model_preset_repo

                    active_key = await app_settings_repo.get_active_model_key()
                    if active_key:
                        preset = await model_preset_repo.get_by_key(active_key)
                        if preset:
                            text += f"Активная модель: {esc(preset['name'])}\n\n"
                        else:
                            text += "⚠️ Активная модель не найдена\n\n"
                    else:
                        text += "⚠️ Активная модель не настроена\n\n"
                except Exception as e:
                    logger.warning(f"Не удалось загрузить активную модель: {e}")

            text += "Настройте бота под ваши предпочтения:"

            await safe_answer(message, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в settings_handler: {e}")
            await message.answer(
                "❌ Не удалось открыть настройки.\n"
                "Попробуйте ещё раз командой /settings."
            )
    
    @router.message(Command("templates", "t"))
    async def templates_handler(message: Message):
        """Обработчик команды /templates"""
        try:
            templates = await template_service.get_all_templates()
            
            if not templates:
                await message.answer("Шаблоны не найдены.")
                return
            
            # Группируем шаблоны по категориям
            from collections import defaultdict
            categories = defaultdict(list)
            for template in templates:
                category = template.category or 'general'
                categories[category].append(template)

            keyboard_buttons = []

            # Добавляем категории
            for category, cat_templates in sorted(categories.items()):
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{category_label(category)} ({len(cat_templates)})",
                    callback_data=f"view_template_category_{category}"
                )])

            # Добавляем кнопку "Все шаблоны"
            keyboard_buttons.append([InlineKeyboardButton(
                text=category_label("all"),
                callback_data="view_template_category_all"
            )])
            
            # Добавляем кнопку создания шаблона
            keyboard_buttons.append([InlineKeyboardButton(
                text="Добавить шаблон",
                callback_data="add_template"
            )])

            # Справка: как устроены шаблоны (переменные, {% if %}, пример)
            keyboard_buttons.append([InlineKeyboardButton(
                text="Как устроены шаблоны",
                callback_data="templates_help"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_answer(message,
                f"<b>Доступные шаблоны:</b> {len(templates)}\n\n"
                "Выберите категорию для просмотра:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в templates_handler: {e}")
            await message.answer(
                "❌ Не удалось загрузить шаблоны.\n"
                "Попробуйте ещё раз командой /templates."
            )
    
    @router.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext):
        """Выход из любого открытого диалога.

        Раньше /cancel рекламировался четырьмя экранами, а работал подстрочной
        проверкой в одном хендлере ввода участников (критика v11): в правке
        шапки он молча становился датой протокола. Роутер команд включён раньше
        карточки сопоставления и правки шапки, поэтому команда забирает текст
        у обоих ловцов.
        """
        try:
            had_dialog = await state.get_state() is not None
            await state.set_state(None)
            await message.answer(
                "Отменено." if had_dialog
                else "Сейчас нечего отменять — пришлите запись, когда будете готовы."
            )
        except Exception as e:
            logger.error(f"Ошибка в cancel_handler: {e}")

    @router.message(Command("feedback", "fb"))
    async def feedback_handler(message: Message):
        """Обработчик команды /feedback"""
        from src.ux.feedback_system import FeedbackUI
        
        keyboard = FeedbackUI.create_feedback_type_keyboard()
        await safe_answer(message,
            FeedbackUI.feedback_intro_text(),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    return router
