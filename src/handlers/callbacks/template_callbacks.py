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


async def _build_flat_template_keyboard(template_service: TemplateService,
                                         callback_prefix: str,
                                         back_button: tuple[str, str] | None = None
                                         ) -> tuple[InlineKeyboardMarkup, list]:
    """Build a flat template list keyboard.

    Returns (keyboard, templates) tuple.
    """
    templates = await template_service.get_all_templates()
    templates.sort(key=lambda t: (not t.is_default, t.name))

    keyboard_buttons = [
        [InlineKeyboardButton(
            text=f"{'⭐ ' if t.is_default else ''}{t.name}",
            callback_data=f"{callback_prefix}{t.id}"
        )] for t in templates
    ]

    if back_button:
        keyboard_buttons.append([InlineKeyboardButton(
            text=back_button[0],
            callback_data=back_button[1]
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    return keyboard, templates


def setup_template_callbacks(user_service: UserService, template_service: TemplateService,
                              llm_service: EnhancedLLMService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для выбора шаблонов"""
    router = Router()

    # Специфичные обработчики выбора шаблона (должны быть ПЕРЕД общим select_template_)
    @router.callback_query(F.data == "select_template_once")
    async def select_template_once_callback(callback: CallbackQuery, state: FSMContext):
        """Разовый выбор шаблона без сохранения по умолчанию"""
        try:
            await _safe_callback_answer(callback)

            templates = await template_service.get_all_templates()

            if not templates:
                await safe_edit_text(callback.message,
                    "❌ **Шаблоны не найдены**\n\n"
                    "Обратитесь к администратору.",
                    parse_mode="Markdown"
                )
                return

            templates.sort(key=lambda t: (not t.is_default, t.name))
            keyboard_buttons = [
                [InlineKeyboardButton(
                    text=t.name,
                    callback_data=f"select_template_id_{t.id}"
                )] for t in templates
            ]
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                "📋 **Выберите шаблон:**\n\nШаблон будет использован для текущей обработки.",
                reply_markup=keyboard, parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Ошибка в select_template_once_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при загрузке шаблонов")

    @router.callback_query(F.data.startswith("select_category_"))
    async def select_category_callback(callback: CallbackQuery, state: FSMContext):
        """Backward-compat: show flat template list (categories removed)"""
        try:
            await _safe_callback_answer(callback)

            keyboard, templates = await _build_flat_template_keyboard(
                template_service,
                callback_prefix="select_template_id_",
            )

            if not templates:
                await safe_edit_text(callback.message,
                    "❌ **Шаблоны не найдены**\n\nОбратитесь к администратору.",
                    parse_mode="Markdown"
                )
                return

            await safe_edit_text(callback.message,
                f"📋 **Все шаблоны**\n\nВыберите шаблон ({len(templates)}):",
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
        """Backward-compat: flat template list for set-default flow (categories removed)"""
        try:
            keyboard, templates = await _build_flat_template_keyboard(
                template_service,
                callback_prefix="set_default_template_",
                back_button=("⬅️ Назад", "settings_default_template"),
            )

            await safe_edit_text(callback.message,
                f"📝 **Все шаблоны**\n\n"
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
        """Backward-compat: flat template list for file flow (categories removed)"""
        try:
            keyboard, templates = await _build_flat_template_keyboard(
                template_service,
                callback_prefix="select_template_",
                back_button=("⬅️ Назад", "back_to_template_categories"),
            )

            await safe_edit_text(callback.message,
                f"📝 **Все шаблоны**\n\n"
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
        """Возврат к плоскому списку шаблонов (categories removed)"""
        try:
            templates = await template_service.get_all_templates()
            templates.sort(key=lambda t: (not t.is_default, t.name))

            keyboard_buttons = []

            # Добавляем кнопку умного выбора
            keyboard_buttons.append([InlineKeyboardButton(
                text="🤖 Умный выбор шаблона",
                callback_data="smart_template_selection"
            )])

            # Плоский список шаблонов
            for t in templates:
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"select_template_{t.id}"
                )])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

            await safe_edit_text(callback.message,
                "📝 **Выберите шаблон для протокола:**\n\n"
                "🤖 **Умный выбор** - ИИ автоматически подберёт подходящий шаблон",
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
        """Backward-compat: flat template list for quick-set flow (categories removed)"""
        try:
            await _safe_callback_answer(callback)

            keyboard, templates = await _build_flat_template_keyboard(
                template_service,
                callback_prefix="quick_template_",
                back_button=("⬅️ Назад", "quick_set_default"),
            )

            await safe_edit_text(callback.message,
                f"⚙️ **Все шаблоны**\n\nВыберите шаблон ({len(templates)}):",
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
