"""
Обработчики callback запросов для ВЫБОРА шаблонов (при обработке файлов).
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, ProcessingService
from src.utils.telegram_safe import safe_edit_text
from .helpers import _safe_callback_answer


def setup_template_callbacks(user_service: UserService, template_service: TemplateService,
                              llm_service: EnhancedLLMService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для выбора шаблонов"""
    router = Router()

    # Специфичные обработчики выбора шаблона (должны быть ПЕРЕД общим select_template_)
    @router.callback_query(F.data == "select_template_once")
    async def select_template_once_callback(callback: CallbackQuery, state: FSMContext):
        """Разовый выбор шаблона без сохранения по умолчанию"""
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

            # Создаем клавиатуру с категориями
            category_names = {
                'management': '👔 Управленческие',
                'product': '🚀 Продуктовые',
                'educational': '📚 Учебные',
                'technical': '⚙️ Технические',
                'general': '📋 Общие',
                'sales': '💼 Продажи'
            }

            # Порядок отображения категорий
            category_order = ['management', 'product', 'educational', 'technical', 'sales', 'general']

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

            # Добавляем кнопки категорий
            for category, cat_templates in sorted_categories:
                category_name = category_names.get(category, f'📁 {category.title()}')
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{category_name} ({len(cat_templates)})",
                    callback_data=f"select_category_{category}"
                )])

            # Добавляем кнопку "Все шаблоны"
            keyboard_buttons.append([InlineKeyboardButton(
                text="📝 Все шаблоны",
                callback_data="select_category_all"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                "📋 **Выберите категорию шаблонов:**\n\n"
                "Выбранный шаблон будет использован только для текущей обработки.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Ошибка в select_template_once_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data.startswith("select_category_"))
    async def select_category_callback(callback: CallbackQuery, state: FSMContext):
        """Показать шаблоны категории для разового использования"""
        try:
            await _safe_callback_answer(callback)

            category = callback.data.replace("select_category_", "")

            # Получаем все шаблоны
            all_templates = await template_service.get_all_templates()

            # Фильтруем по категории
            if category == "all":
                templates = all_templates
                category_title = "Все шаблоны"
            else:
                templates = [t for t in all_templates if (t.category or 'general') == category]
                category_names = {
                    'management': '👔 Управленческие',
                    'product': '🚀 Продуктовые',
                    'educational': '📚 Учебные',
                    'technical': '⚙️ Технические',
                    'general': '📋 Общие',
                    'sales': '💼 Продажи'
                }
                category_title = category_names.get(category, category.title())

            # Сортируем шаблоны
            templates.sort(key=lambda t: (not t.is_default, t.name))

            # Создаем клавиатуру с шаблонами
            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"select_template_id_{t.id}"
                )] for t in templates
            ]

            keyboard_buttons.append([InlineKeyboardButton(
                text="⬅️ Назад к категориям",
                callback_data="select_template_once"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                f"📋 **{category_title}**\n\n"
                f"Выберите шаблон ({len(templates)}):",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Ошибка в select_category_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data.startswith("select_template_id_"))
    async def select_template_id_callback(callback: CallbackQuery, state: FSMContext):
        """Использовать выбранный шаблон без сохранения по умолчанию"""
        from .llm_callbacks import _show_llm_selection

        try:
            await _safe_callback_answer(callback)

            template_id = int(callback.data.replace("select_template_id_", ""))
            template = await template_service.get_template_by_id(template_id)

            if not template:
                await safe_edit_text(callback.message,
                    "❌ **Ошибка**\n\n"
                    "Шаблон не найден.",
                    parse_mode="Markdown"
                )
                return

            # Сохраняем шаблон ТОЛЬКО в состояние (НЕ как default_template_id пользователя)
            await state.update_data(template_id=template_id, use_smart_selection=False)

            await safe_edit_text(callback.message,
                f"📋 **Выбран шаблон: {template.name}**\n\n"
                "Шаблон будет использован для текущей обработки.\n\n"
                "⏳ Переходим к выбору ИИ для обработки...",
                parse_mode="Markdown"
            )

            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в select_template_id_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при выборе шаблона")

    @router.callback_query(F.data.startswith("select_template_"))
    async def select_template_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора шаблона"""
        from .llm_callbacks import _show_llm_selection

        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)

            template_id = int(callback.data.replace("select_template_", ""))
            await state.update_data(template_id=template_id)

            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в select_template_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при выборе шаблона")

    @router.callback_query(F.data.startswith("use_default_template_"))
    async def use_default_template_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик использования шаблона по умолчанию"""
        from .llm_callbacks import _show_llm_selection

        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)

            template_id = int(callback.data.replace("use_default_template_", ""))
            await state.update_data(template_id=template_id)

            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в use_default_template_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при использовании шаблона по умолчанию")

    @router.callback_query(F.data == "show_all_templates")
    async def show_all_templates_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик показа всех шаблонов"""
        try:
            from services import TemplateService
            template_service_local = TemplateService()

            templates = await template_service_local.get_all_templates()

            if not templates:
                await safe_edit_text(callback.message, "❌ Шаблоны не найдены. Обратитесь к администратору.")
                return

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"select_template_{t.id}"
                )]
                for t in templates
            ])

            await safe_edit_text(callback.message,
                "📝 Выберите шаблон для протокола:",
                reply_markup=keyboard
            )

        except Exception as e:
            logger.error(f"Ошибка в show_all_templates_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data.startswith("template_category_"))
    async def template_category_callback(callback: CallbackQuery):
        """Обработчик выбора категории шаблонов"""
        try:
            category = callback.data.replace("template_category_", "")

            # Получаем все шаблоны
            all_templates = await template_service.get_all_templates()

            # Фильтруем по категории
            if category == "all":
                templates = all_templates
                category_title = "Все шаблоны"
            else:
                templates = [t for t in all_templates if (t.category or 'general') == category]
                category_names = {
                    'management': '👔 Управленческие',
                    'product': '🚀 Продуктовые',
                    'educational': '📚 Учебные',
                    'technical': '⚙️ Технические',
                    'general': '📋 Общие',
                    'sales': '💼 Продажи'
                }
                category_title = category_names.get(category, category.title())

            # Сортируем шаблоны: is_default сначала, затем по имени
            templates.sort(key=lambda t: (not t.is_default, t.name))

            # Создаем клавиатуру с шаблонами
            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"set_default_template_{t.id}"
                )] for t in templates
            ]

            keyboard_buttons.extend([
                [InlineKeyboardButton(
                    text="⬅️ Назад к категориям",
                    callback_data="settings_default_template"
                )]
            ])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                f"📝 **{category_title}**\n\n"
                f"Найдено шаблонов: {len(templates)}\n"
                "Выберите шаблон для установки по умолчанию:",
                reply_markup=keyboard
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в template_category_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data.startswith("file_template_category_"))
    async def file_template_category_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора категории шаблонов для файла"""
        try:
            category = callback.data.replace("file_template_category_", "")

            # Получаем все шаблоны
            all_templates = await template_service.get_all_templates()

            # Фильтруем по категории
            if category == "all":
                templates = all_templates
                category_title = "Все шаблоны"
            else:
                templates = [t for t in all_templates if (t.category or 'general') == category]
                category_names = {
                    'management': '👔 Управленческие',
                    'product': '🚀 Продуктовые',
                    'technical': '⚙️ Технические',
                    'general': '📋 Общие',
                    'sales': '💼 Продажи'
                }
                category_title = category_names.get(category, category.title())

            # Сортируем шаблоны: is_default сначала, затем по имени
            templates.sort(key=lambda t: (not t.is_default, t.name))

            # Создаем клавиатуру с шаблонами
            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"select_template_{t.id}"
                )] for t in templates
            ]

            keyboard_buttons.append([InlineKeyboardButton(
                text="⬅️ Назад к категориям",
                callback_data="back_to_template_categories"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                f"📝 **{category_title}**\n\n"
                f"Найдено шаблонов: {len(templates)}\n"
                "Выберите шаблон:",
                reply_markup=keyboard
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в file_template_category_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data == "back_to_template_categories")
    async def back_to_template_categories_callback(callback: CallbackQuery, state: FSMContext):
        """Возврат к выбору категорий шаблонов"""
        try:
            templates = await template_service.get_all_templates()

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

            # Добавляем кнопку умного выбора
            keyboard_buttons.append([InlineKeyboardButton(
                text="🤖 Умный выбор шаблона",
                callback_data="smart_template_selection"
            )])

            # Добавляем категории
            for category, cat_templates in sorted(categories.items()):
                category_name = category_names.get(category, f'📁 {category.title()}')
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{category_name} ({len(cat_templates)})",
                    callback_data=f"file_template_category_{category}"
                )])

            # Добавляем кнопку "Все шаблоны"
            keyboard_buttons.append([InlineKeyboardButton(
                text="📝 Все шаблоны",
                callback_data="file_template_category_all"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                "📝 **Выберите шаблон для протокола:**\n\n"
                "🤖 **Умный выбор** - ИИ автоматически подберёт подходящий шаблон\n"
                "📁 **Категории** - выберите тип встречи",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в back_to_template_categories_callback: {e}")
            await callback.answer("❌ Произошла ошибка")

    @router.callback_query(F.data == "smart_template_selection")
    async def smart_template_selection_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик умного выбора шаблона через ML"""
        from .llm_callbacks import _show_llm_selection

        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)

            # Не устанавливаем template_id - позволяем ML-селектору выбрать после транскрипции
            await state.update_data(template_id=0, use_smart_selection=True)

            await safe_edit_text(callback.message,
                "🤖 **Умный выбор шаблона активирован!**\n\n"
                "ИИ проанализирует содержание вашей встречи и автоматически подберёт "
                "наиболее подходящий шаблон после транскрипции.\n\n"
                "⏳ Переходим к выбору ИИ для обработки...",
                parse_mode="Markdown"
            )

            # Показываем выбор LLM используя функцию для callback
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в smart_template_selection_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при активации умного выбора")

    @router.callback_query(F.data == "quick_smart_select")
    async def quick_smart_selection_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик быстрого умного выбора шаблона"""
        from .llm_callbacks import _show_llm_selection

        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)

            # Устанавливаем умный выбор
            await state.update_data(template_id=0, use_smart_selection=True)

            await safe_edit_text(callback.message,
                "🤖 **Умный выбор шаблона**\n\n"
                "ИИ автоматически подберёт подходящий шаблон после транскрипции.\n\n"
                "⏳ Переходим к выбору ИИ для обработки...",
                parse_mode="Markdown"
            )

            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в quick_smart_selection_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при выборе умного шаблона")

    @router.callback_query(F.data == "use_saved_default")
    async def use_saved_default_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик использования сохранённого шаблона по умолчанию"""
        from .llm_callbacks import _show_llm_selection

        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)

            # Получаем пользователя и его шаблон по умолчанию
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)

            if not user or not user.default_template_id:
                await safe_edit_text(callback.message,
                    "❌ **Ошибка**\n\n"
                    "У вас не установлен шаблон по умолчанию.",
                    parse_mode="Markdown"
                )
                return

            # Если сохранён умный выбор (template_id = 0)
            if user.default_template_id == 0:
                await state.update_data(template_id=0, use_smart_selection=True)
                await safe_edit_text(callback.message,
                    "🤖 **Используется Умный выбор шаблона**\n\n"
                    "ИИ автоматически подберёт подходящий шаблон после транскрипции.\n\n"
                    "⏳ Переходим к выбору ИИ для обработки...",
                    parse_mode="Markdown"
                )
            else:
                # Используем конкретный шаблон
                template = await template_service.get_template_by_id(user.default_template_id)
                if not template:
                    await safe_edit_text(callback.message,
                        "❌ **Ошибка**\n\n"
                        "Сохранённый шаблон не найден.",
                        parse_mode="Markdown"
                    )
                    return

                await state.update_data(template_id=template.id, use_smart_selection=False)
                await safe_edit_text(callback.message,
                    f"📋 **Используется шаблон: {template.name}**\n\n"
                    "⏳ Переходим к выбору ИИ для обработки...",
                    parse_mode="Markdown"
                )

            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в use_saved_default_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при использовании шаблона")

    @router.callback_query(F.data == "back_to_template_selection")
    async def back_to_template_selection_callback(callback: CallbackQuery, state: FSMContext):
        """Вернуться к выбору способа создания протокола"""
        try:
            await _safe_callback_answer(callback)

            # Повторно показываем меню выбора
            from src.handlers.message_handlers import _show_template_selection_step2

            state_data = await state.get_data()
            participants_count = len(state_data.get('participants_list', [])) if state_data.get('participants_list') else None

            await _show_template_selection_step2(callback.message, template_service, state, participants_count, real_user_id=callback.from_user.id)

        except Exception as e:
            logger.error(f"Ошибка в back_to_template_selection_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("quick_category_"))
    async def quick_category_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора категории для быстрой установки шаблона"""
        try:
            await _safe_callback_answer(callback)

            category = callback.data.replace("quick_category_", "")

            # Получаем все шаблоны
            all_templates = await template_service.get_all_templates()

            # Фильтруем по категории
            if category == "all":
                templates = all_templates
                category_title = "Все шаблоны"
            else:
                templates = [t for t in all_templates if (t.category or 'general') == category]
                category_names = {
                    'management': '👔 Управленческие',
                    'product': '🚀 Продуктовые',
                    'technical': '⚙️ Технические',
                    'general': '📋 Общие',
                    'sales': '💼 Продажи'
                }
                category_title = category_names.get(category, category.title())

            # Сортируем шаблоны
            templates.sort(key=lambda t: (not t.is_default, t.name))

            # Создаем клавиатуру с шаблонами
            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"quick_template_{t.id}"
                )] for t in templates
            ]

            keyboard_buttons.append([InlineKeyboardButton(
                text="⬅️ Назад к категориям",
                callback_data="quick_set_default"
            )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                f"⚙️ **{category_title}**\n\n"
                f"Выберите шаблон ({len(templates)}):",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Ошибка в quick_category_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data.startswith("quick_template_"))
    async def quick_template_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора конкретного шаблона для быстрой установки"""
        from .llm_callbacks import _show_llm_selection

        try:
            await _safe_callback_answer(callback)

            template_ref = callback.data.replace("quick_template_", "")

            # Обрабатываем специальный случай "smart"
            if template_ref == "smart":
                # Сохраняем умный выбор как шаблон по умолчанию (id = 0)
                await template_service.set_user_default_template(callback.from_user.id, 0)
                await state.update_data(template_id=0, use_smart_selection=True)

                await safe_edit_text(callback.message,
                    "✅ **Умный выбор установлен по умолчанию**\n\n"
                    "🤖 ИИ автоматически подберёт подходящий шаблон.\n\n"
                    "⏳ Переходим к выбору ИИ для обработки...",
                    parse_mode="Markdown"
                )
            else:
                # Обрабатываем выбор конкретного шаблона
                template_id = int(template_ref)
                template = await template_service.get_template_by_id(template_id)

                if not template:
                    await safe_edit_text(callback.message,
                        "❌ **Ошибка**\n\n"
                        "Шаблон не найден.",
                        parse_mode="Markdown"
                    )
                    return

                # Сохраняем шаблон как по умолчанию
                await template_service.set_user_default_template(callback.from_user.id, template_id)
                await state.update_data(template_id=template_id, use_smart_selection=False)

                await safe_edit_text(callback.message,
                    f"✅ **Шаблон установлен: {template.name}**\n\n"
                    f"Шаблон сохранён по умолчанию и будет использован для обработки.\n\n"
                    "⏳ Переходим к выбору ИИ для обработки...",
                    parse_mode="Markdown"
                )

            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)

        except Exception as e:
            logger.error(f"Ошибка в quick_template_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при установке шаблона")

    return router
