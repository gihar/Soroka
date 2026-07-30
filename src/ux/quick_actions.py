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

from src.services import TemplateService
from src.utils.telegram_safe import safe_answer
from src.utils.template_sort import sort_templates_by_name

# Единый источник подписи входа в меню админа: кнопка главного меню, фильтр
# текст-хендлера и зеркало в message_handlers ссылаются сюда, чтобы подпись не
# разъехалась (⚙ занят «Настройками», поэтому вход в админку — без глифа).
ADMIN_MENU_BUTTON = "Меню администратора"


class QuickActionsUI:
    """Интерфейс быстрых действий"""
    
    @staticmethod
    def create_main_menu(user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
        """Создать главное меню с быстрыми действиями"""
        from src.utils.admin_utils import is_admin
        
        keyboard = [
            [
                KeyboardButton(text="Мои шаблоны"),
                KeyboardButton(text="⚙️ Настройки")
            ],
            [
                KeyboardButton(text="Помощь"),
                KeyboardButton(text="Обратная связь")
            ]
        ]
        
        # Добавляем кнопку администратора только для админов
        if user_id and is_admin(user_id):
            keyboard.append([
                KeyboardButton(text=ADMIN_MENU_BUTTON)
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
            "<b>Файл получен</b>\n\n"
            "<b>Быстрая обработка</b> — умный шаблон и сохранённые настройки\n"
            "<b>Настроить</b> — выбрать участников, шаблон, модель"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Быстрая обработка",
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
                    text="Модель ИИ",
                    callback_data="settings_active_model",
                )
            ])

        buttons.extend([
            [
                InlineKeyboardButton(
                    text="Вывод протокола",
                    callback_data="settings_protocol_output",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Шаблон по умолчанию",
                    callback_data="settings_default_template",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сопоставление спикеров",
                    callback_data="settings_speaker_mapping",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Статистика",
                    callback_data="settings_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сбросить настройки",
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
                    text="Статистика системы",
                    callback_data="admin_status"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Проверка здоровья",
                    callback_data="admin_health"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Производительность",
                    callback_data="admin_performance"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Управление файлами",
                    callback_data="admin_cleanup"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Режим транскрипции",
                    callback_data="admin_transcription"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сброс компонентов",
                    callback_data="admin_reset"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Экспорт статистики",
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
    
    @router.message(F.text == "Мои шаблоны")
    async def my_templates_button_handler(message: Message):
        """Обработчик кнопки шаблонов"""
        try:
            template_service = TemplateService()
            templates = await template_service.get_all_templates()

            if not templates:
                await message.answer("Шаблоны не найдены.")
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
                text="Добавить шаблон",
                callback_data="add_template"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_answer(message,
                f"<b>Доступные шаблоны ({len(templates)}):</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в my_templates_button_handler: {e}")
            await message.answer(
                "❌ Не удалось загрузить шаблоны.\n"
                "Попробуйте ещё раз — если повторится, откройте /templates."
            )
    
    @router.message(F.text == "⚙️ Настройки")
    async def settings_button_handler(message: Message):
        """Обработчик кнопки настроек"""
        from src.utils.admin_utils import is_admin as _is_admin
        keyboard = QuickActionsUI.create_settings_menu(
            is_admin=_is_admin(message.from_user.id)
        )
        await message.answer(
            "⚙️ <b>Настройки бота</b>\n\n"
            "Настройте бота под ваши предпочтения:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    
    @router.message(F.text == "Помощь")
    async def help_button_handler(message: Message):
        """Обработчик кнопки помощи"""
        from src.ux.message_builder import MessageBuilder
        help_text = MessageBuilder.help_message()
        await safe_answer(message, help_text, parse_mode="HTML")
    
    @router.message(F.text == "Обратная связь")
    async def feedback_button_handler(message: Message):
        """Обработчик кнопки обратной связи"""
        from src.ux.feedback_system import FeedbackUI
        keyboard = FeedbackUI.create_feedback_type_keyboard()
        await safe_answer(message,
            FeedbackUI.feedback_intro_text(),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    @router.message(F.text == ADMIN_MENU_BUTTON)
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
            "<b>Меню администратора</b>\n\n"
            "Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    return router
