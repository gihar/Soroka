"""
Обработчики callback запросов для УПРАВЛЕНИЯ шаблонами
(просмотр, удаление, установка/сброс шаблона по умолчанию).
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from services import ProcessingService, TemplateService, UserService
from src.utils.telegram_safe import safe_edit_text
from src.utils.template_sort import category_label, sort_templates_by_name
from src.ux.keyboards import build_template_picker

from .helpers import _safe_callback_answer


def setup_template_mgmt_callbacks(user_service: UserService, template_service: TemplateService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для управления шаблонами"""
    router = Router()

    @router.callback_query(F.data.startswith("view_template_category_"))
    async def view_template_category_callback(callback: CallbackQuery):
        """Список шаблонов категории — кнопка категории фильтрует по-настоящему."""
        try:
            category = callback.data.replace("view_template_category_", "")
            templates = await template_service.get_all_templates()
            if category != "all":
                templates = [
                    t for t in templates
                    if (t.category or "general") == category
                ]
            templates = sort_templates_by_name(templates)

            title = category_label(category)

            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=t.name,
                    callback_data=f"view_template_{t.id}"
                )] for t in templates
            ]
            keyboard_buttons.append([InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="back_to_templates"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            await safe_edit_text(callback.message,
                f"{title} ({len(templates)})",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в view_template_category_callback: {e}")
            await callback.answer("❌ Ошибка при загрузке шаблонов")

    @router.callback_query(F.data == "templates_help")
    async def templates_help_callback(callback: CallbackQuery):
        """Справка по устройству шаблонов: переменные, {% if %}, пример."""
        try:
            from src.ux.message_builder import MessageBuilder

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_templates")
            ]])
            await safe_edit_text(
                callback.message,
                MessageBuilder.templates_help_message(),
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
            await _safe_callback_answer(callback)
        except Exception as e:
            logger.error(f"Ошибка в templates_help_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("view_template_"))
    async def view_template_callback(callback: CallbackQuery):
        """Обработчик просмотра шаблона"""
        try:
            template_id = int(callback.data.replace("view_template_", ""))
            template = await template_service.get_template_by_id(template_id)
            # Проверяем права удаления: владелец и не базовый шаблон
            try:
                user = await user_service.get_user_by_telegram_id(callback.from_user.id)
                owned_ids = set()
                if user:
                    owned_ids.add(user.id)
                owned_ids.add(callback.from_user.id)  # поддержка legacy-шаблонов
                can_delete = (not template.is_default) and (template.created_by in owned_ids)
            except Exception:
                can_delete = False

            text = f"📝 **{template.name}**\n\n"
            if template.description:
                text += f"*Описание:* {template.description}\n\n"

            text += f"```\n{template.content}\n```"

            # Кнопки: удалить показываем только владельцу
            rows = []
            if can_delete:
                rows.append([InlineKeyboardButton(
                    text="🗑 Удалить шаблон",
                    callback_data=f"delete_template_{template.id}"
                )])
            rows.append([InlineKeyboardButton(
                text="🔙 Назад к списку шаблонов",
                callback_data="back_to_templates"
            )])
            keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

            await safe_edit_text(callback.message, text, parse_mode="Markdown", reply_markup=keyboard)
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в view_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при просмотре шаблона")

    @router.callback_query(F.data.startswith("delete_template_"))
    async def delete_template_prompt_callback(callback: CallbackQuery):
        """Показываем подтверждение удаления"""
        try:
            template_id = int(callback.data.replace("delete_template_", ""))
            template = await template_service.get_template_by_id(template_id)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_template_{template_id}"),
                    InlineKeyboardButton(text="↩️ Отмена", callback_data=f"view_template_{template_id}")
                ]
            ])
            await safe_edit_text(callback.message,
                f"Вы уверены, что хотите удалить шаблон:\n\n• {template.name}",
                reply_markup=keyboard
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в delete_template_prompt_callback: {e}")
            await callback.answer("❌ Не удалось показать подтверждение удаления")

    @router.callback_query(F.data.startswith("confirm_delete_template_"))
    async def confirm_delete_template_callback(callback: CallbackQuery):
        """Удаление шаблона после подтверждения"""
        try:
            template_id = int(callback.data.replace("confirm_delete_template_", ""))
            success = await template_service.delete_template(callback.from_user.id, template_id)

            if success:
                # Показываем обновленный список
                templates = await template_service.get_all_templates()
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t.name,
                        callback_data=f"view_template_{t.id}"
                    )] for t in templates
                ] + [[InlineKeyboardButton(text="➕ Добавить шаблон", callback_data="add_template")]])

                await safe_edit_text(callback.message,
                    "🗑 Шаблон удалён.\n\n📝 **Доступные шаблоны:**",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                await callback.answer()
            else:
                await callback.answer("❌ Не удалось удалить шаблон")
        except Exception as e:
            logger.error(f"Ошибка в confirm_delete_template_callback: {e}")
            await callback.answer("❌ Ошибка при удалении шаблона")

    @router.callback_query(F.data == "back_to_templates")
    async def back_to_templates_callback(callback: CallbackQuery):
        """Возврат к категориям шаблонов"""
        try:
            templates = await template_service.get_all_templates()

            # Группируем шаблоны по категориям
            from collections import defaultdict
            categories = defaultdict(list)
            for template in templates:
                category = template.category or 'general'
                categories[category].append(template)

            # Порядок отображения категорий (только реально существующие)
            category_order = ['management', 'educational', 'technical', 'general']

            keyboard_buttons = []

            # Сортируем категории согласно заданному порядку
            sorted_categories = []
            # Сначала добавляем категории из списка порядка
            for cat in category_order:
                if cat in categories:
                    sorted_categories.append((cat, categories[cat]))

            # Затем добавляем остальные категории (если есть), отсортированные по алфавиту
            for cat, tmpls in sorted(categories.items()):
                if cat not in category_order:
                    sorted_categories.append((cat, tmpls))

            # Добавляем категории
            for category, cat_templates in sorted_categories:
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
                text="➕ Добавить шаблон",
                callback_data="add_template"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                f"📝 **Доступные шаблоны:** {len(templates)}\n\n"
                "Выберите категорию для просмотра:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в back_to_templates_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data == "settings_default_template")
    async def settings_default_template_callback(callback: CallbackQuery):
        """Обработчик настройки шаблона по умолчанию"""
        try:
            # Получаем все доступные шаблоны
            all_templates = await template_service.get_all_templates()

            if not all_templates:
                # Если нет шаблонов, предлагаем создать
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="📝 Создать шаблон",
                        callback_data="create_template"
                    )],
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings"
                    )]
                ])

                await safe_edit_text(callback.message,
                    "📝 **Шаблон по умолчанию**\n\n"
                    "У вас пока нет доступных шаблонов.\n"
                    "Создайте шаблон, чтобы установить его по умолчанию:",
                    reply_markup=keyboard
                )
            else:
                # Единый пикер: умный выбор сверху, сетка 2 колонки, футер снизу.
                keyboard = build_template_picker(
                    all_templates,
                    lambda t: f"set_default_template_{t.id}",
                    top_rows=[[InlineKeyboardButton(
                        text="🤖 Умный выбор (рекомендуется)",
                        callback_data="set_default_template_0",
                    )]],
                    bottom_rows=[
                        [InlineKeyboardButton(
                            text="🔄 Сбросить шаблон по умолчанию",
                            callback_data="reset_default_template",
                        )],
                        [InlineKeyboardButton(
                            text="⬅️ Назад к настройкам",
                            callback_data="back_to_settings",
                        )],
                    ],
                )

                await safe_edit_text(callback.message,
                    "📝 **Шаблон по умолчанию**\n\n"
                    "Выберите шаблон или доверьте выбор ИИ:",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в settings_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")

    @router.callback_query(F.data.startswith("set_default_template_"))
    async def set_default_template_callback(callback: CallbackQuery):
        """Обработчик установки шаблона по умолчанию"""
        try:
            template_id = int(callback.data.replace("set_default_template_", ""))

            # Устанавливаем шаблон по умолчанию
            success = await template_service.set_user_default_template(callback.from_user.id, template_id)

            if success:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings"
                    )]
                ])

                # Если template_id = 0, это "Умный выбор"
                if template_id == 0:
                    await safe_edit_text(callback.message,
                        "**Шаблон по умолчанию: умный выбор**\n"
                        "Подходящий шаблон подбирается по содержанию каждой встречи.",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                else:
                    # Получаем информацию о конкретном шаблоне
                    template = await template_service.get_template_by_id(template_id)

                    await safe_edit_text(callback.message,
                        f"**Шаблон по умолчанию: {template.name}**\n"
                        "Применяется автоматически при обработке записи.",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
            else:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings"
                    )]
                ])

                await safe_edit_text(callback.message,
                    "❌ **Ошибка установки шаблона**\n\n"
                    "Не удалось установить шаблон по умолчанию.\n"
                    "Возможно, шаблон недоступен или произошла ошибка.",
                    reply_markup=keyboard
                )

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в set_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при установке шаблона")

    @router.callback_query(F.data == "reset_default_template")
    async def reset_default_template_callback(callback: CallbackQuery):
        """Обработчик сброса шаблона по умолчанию"""
        try:
            # Сбрасываем шаблон по умолчанию через template_service
            success = await template_service.reset_user_default_template(callback.from_user.id)

            if success:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings"
                    )]
                ])

                await safe_edit_text(callback.message,
                    "**Шаблон по умолчанию сброшен**\n"
                    "Перед обработкой бот будет спрашивать шаблон.",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                await callback.answer()
            else:
                await callback.answer("❌ Не удалось сбросить шаблон по умолчанию")

        except Exception as e:
            logger.error(f"Ошибка в reset_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе шаблона")

    @router.callback_query(F.data == "quick_set_default")
    async def quick_set_default_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик быстрой установки шаблона по умолчанию"""
        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)

            # Получаем все шаблоны
            templates = await template_service.get_all_templates()

            if not templates:
                await safe_edit_text(callback.message,
                    "❌ **Шаблоны не найдены**\n\n"
                    "Обратитесь к администратору.",
                    parse_mode="Markdown"
                )
                return

            # Группируем шаблоны по категориям
            from collections import defaultdict
            categories = defaultdict(list)
            for template in templates:
                category = template.category or 'general'
                categories[category].append(template)

            keyboard_buttons = []

            # Добавляем опцию "Умный выбор" первой
            keyboard_buttons.append([InlineKeyboardButton(
                text="🤖 Умный выбор (рекомендуется)",
                callback_data="quick_template_smart"
            )])

            # Добавляем категории
            for category, cat_templates in sorted(categories.items()):
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{category_label(category)} ({len(cat_templates)})",
                    callback_data=f"quick_category_{category}"
                )])

            # Добавляем кнопку "Все шаблоны"
            keyboard_buttons.append([InlineKeyboardButton(
                text=category_label("all"),
                callback_data="quick_category_all"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                "⚙️ **Выберите шаблон по умолчанию:**\n\n"
                "Выбранный шаблон будет сохранён и использован для обработки этого файла.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Ошибка в quick_set_default_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при загрузке шаблонов")

    return router
