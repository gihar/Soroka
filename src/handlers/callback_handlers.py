"""
Обработчики callback запросов
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, ProcessingService
from src.utils.pdf_converter import convert_markdown_to_pdf
from src.utils.telegram_safe import safe_edit_text


async def _safe_callback_answer(callback: CallbackQuery, text: str = None):
    """Безопасный ответ на callback query с обработкой устаревших запросов"""
    try:
        await callback.answer(text=text)
    except Exception as e:
        error_str = str(e).lower()
        # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
        error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
        if "query is too old" in error_str or "query id is invalid" in error_str:
            logger.debug(f"Callback query устарел: {error_msg_safe}")
        else:
            logger.warning(f"Ошибка ответа на callback: {error_msg_safe}")


def setup_callback_handlers(user_service: UserService, template_service: TemplateService,
                           llm_service: EnhancedLLMService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов"""
    router = Router()
    
    @router.callback_query(F.data.startswith("set_llm_"))
    async def set_llm_callback(callback: CallbackQuery):
        """Обработчик выбора LLM"""
        try:
            llm_provider = callback.data.replace("set_llm_", "")
            
            await user_service.update_user_llm_preference(callback.from_user.id, llm_provider)
            
            available_providers = llm_service.get_available_providers()
            provider_name = available_providers.get(llm_provider, llm_provider)
            
            await safe_edit_text(callback.message, 
                f"✅ LLM провайдер изменен на: {provider_name}\n\n"
                f"Теперь этот LLM будет использоваться автоматически для всех обработок."
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в set_llm_callback: {e}")
            await callback.answer("❌ Произошла ошибка при изменении настроек")
    
    @router.callback_query(F.data == "reset_llm_preference")
    async def reset_llm_preference_callback(callback: CallbackQuery):
        """Обработчик сброса предпочтений LLM"""
        try:
            await user_service.update_user_llm_preference(callback.from_user.id, None)
            
            await safe_edit_text(callback.message, 
                "🔄 Предпочтения LLM сброшены.\n\n"
                "Теперь бот будет спрашивать выбор LLM при каждой обработке файла."
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в reset_llm_preference_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе настроек")
    
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
            for cat, templates in sorted(categories.items()):
                if cat not in category_order:
                    sorted_categories.append((cat, templates))
            
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
            template_service = TemplateService()
            
            templates = await template_service.get_all_templates()
            
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
    
    @router.callback_query(F.data.startswith("select_llm_"))
    async def select_llm_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора LLM для обработки"""
        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)
            
            llm_provider = callback.data.replace("select_llm_", "")
            
            # Сохраняем выбор пользователя как предпочтение
            await user_service.update_user_llm_preference(callback.from_user.id, llm_provider)
            await state.update_data(llm_provider=llm_provider)
            
            # Начинаем обработку
            await _process_file(callback, state, processing_service)
            
        except Exception as e:
            logger.error(f"Ошибка в select_llm_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при выборе LLM")
    
    @router.callback_query(F.data.startswith("set_transcription_mode_"))
    async def set_transcription_mode_callback(callback: CallbackQuery):
        """Обработчик переключения режима транскрипции"""
        try:
            mode = callback.data.replace("set_transcription_mode_", "")
            
            # Обновляем настройки
            from config import settings
            settings.transcription_mode = mode
            
            mode_names = {
                "local": "Локальная (Whisper)",
                "cloud": "Облачная (Groq)",
                "hybrid": "Гибридная (Groq + диаризация)",
                "speechmatics": "Speechmatics",
                "deepgram": "Deepgram",
                "leopard": "Leopard (Picovoice)"
            }
            
            mode_name = mode_names.get(mode, mode)
            
            await safe_edit_text(callback.message, 
                f"✅ **Режим транскрипции изменен на:** {mode_name}\n\n"
                f"Новый режим будет использоваться для всех последующих обработок файлов.",
                parse_mode="Markdown"
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в set_transcription_mode_callback: {e}")
            await callback.answer("❌ Произошла ошибка при изменении режима транскрипции")
    
    @router.callback_query(F.data.startswith("view_template_category_"))
    async def view_template_category_callback(callback: CallbackQuery):
        """Обработчик просмотра шаблонов по категории"""
        try:
            category = callback.data.replace("view_template_category_", "")
            
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
                    callback_data=f"view_template_{t.id}"
                )] for t in templates
            ]
            
            keyboard_buttons.extend([
                [InlineKeyboardButton(
                    text="⬅️ Назад к категориям",
                    callback_data="back_to_templates"
                )]
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            await safe_edit_text(callback.message, 
                f"📝 **{category_title}**\n\n"
                f"Найдено шаблонов: {len(templates)}",
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в view_template_category_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке шаблонов")
    
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
                        text=f"{'⭐ ' if t.is_default else ''}{t.name}",
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
            for cat, templates in sorted(categories.items()):
                if cat not in category_order:
                    sorted_categories.append((cat, templates))
            
            # Добавляем категории
            for category, cat_templates in sorted_categories:
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
    
    # Обработчики для кнопок настроек
    @router.callback_query(F.data == "settings_preferred_llm")
    async def settings_preferred_llm_callback(callback: CallbackQuery):
        """Обработчик настройки предпочитаемого ИИ"""
        try:
            available_providers = llm_service.get_available_providers()
            
            # Создаем клавиатуру для выбора LLM
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🤖 {provider_name}",
                    callback_data=f"set_llm_{provider_key}"
                )] for provider_key, provider_name in available_providers.items()
            ] + [
                [InlineKeyboardButton(
                    text="🔄 Сбросить предпочтение",
                    callback_data="reset_llm_preference"
                )],
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])
            
            await safe_edit_text(callback.message, 
                "🤖 **Выберите предпочитаемый ИИ**\n\n"
                "Этот ИИ будет использоваться автоматически для всех обработок:",
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в settings_preferred_llm_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")

    @router.callback_query(F.data == "settings_openai_model")
    async def settings_openai_model_callback(callback: CallbackQuery):
        """Обработчик меню выбора модели OpenAI"""
        try:
            from config import settings as app_settings
            models = getattr(app_settings, 'openai_models', [])
            if not models or len(models) == 0:
                await safe_edit_text(callback.message, 
                    "❌ Не настроены модели OpenAI.\n\n"
                    "Добавьте переменную окружения `OPENAI_MODELS` с перечнем пресетов.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                    ])
                )
                await callback.answer()
                return
            # Получаем текущего пользователя и его выбор
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            selected_key = getattr(user, 'preferred_openai_model_key', None) if user else None

            keyboard_rows = []
            for p in models:
                label = f"{'✅ ' if selected_key == p.key else ''}{p.name}"
                keyboard_rows.append([InlineKeyboardButton(text=label, callback_data=f"set_openai_model_{p.key}")])
            keyboard_rows.append([InlineKeyboardButton(text="🔄 Сбросить выбор модели", callback_data="reset_openai_model_preference")])
            keyboard_rows.append([InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")])

            await safe_edit_text(callback.message, 
                "🧠 **Модель OpenAI**\n\n"
                "Выберите модель, которая будет использоваться при провайдере OpenAI:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в settings_openai_model_callback: {e}")
            await callback.answer("❌ Не удалось загрузить модели OpenAI")

    @router.callback_query(F.data.startswith("set_openai_model_"))
    async def set_openai_model_callback(callback: CallbackQuery):
        """Устанавливает предпочитаемую модель OpenAI"""
        try:
            model_key = callback.data.replace("set_openai_model_", "")
            await user_service.update_user_openai_model_preference(callback.from_user.id, model_key)
            # Находим человекочитаемое имя модели из настроек
            try:
                from config import settings as app_settings
                preset = next((p for p in getattr(app_settings, 'openai_models', []) if p.key == model_key), None)
                model_name = preset.name if preset else model_key
            except Exception:
                model_name = model_key
            await safe_edit_text(callback.message, 
                f"✅ Модель OpenAI обновлена: {model_name}.\n\n"
                "Она будет использоваться при выборе провайдера OpenAI.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                ])
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в set_openai_model_callback: {e}")
            await callback.answer("❌ Не удалось сохранить выбор модели")

    @router.callback_query(F.data == "reset_openai_model_preference")
    async def reset_openai_model_preference_callback(callback: CallbackQuery):
        """Сбрасывает предпочитаемую модель OpenAI"""
        try:
            await user_service.update_user_openai_model_preference(callback.from_user.id, None)
            await safe_edit_text(callback.message, 
                "🔄 Выбор модели OpenAI сброшен.\n\n"
                "Будет использован пресет по умолчанию.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                ])
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в reset_openai_model_preference_callback: {e}")
            await callback.answer("❌ Не удалось сбросить выбор модели")
    
    
    
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
                # Группируем шаблоны по категориям
                from collections import defaultdict
                categories = defaultdict(list)
                for template in all_templates:
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
                
                # ПЕРВАЯ кнопка - Умный выбор (рекомендуется)
                keyboard_buttons.append([InlineKeyboardButton(
                    text="🤖 Умный выбор (рекомендуется)",
                    callback_data="set_default_template_0"  # 0 = умный выбор
                )])
                
                # Сортируем категории согласно заданному порядку
                sorted_categories = []
                # Сначала добавляем категории из списка порядка
                for cat in category_order:
                    if cat in categories:
                        sorted_categories.append((cat, categories[cat]))
                
                # Затем добавляем остальные категории (если есть), отсортированные по алфавиту
                for cat, templates in sorted(categories.items()):
                    if cat not in category_order:
                        sorted_categories.append((cat, templates))
                
                # Категории шаблонов
                for category, templates in sorted_categories:
                    category_name = category_names.get(category, f'📁 {category.title()}')
                    keyboard_buttons.append([InlineKeyboardButton(
                        text=f"{category_name} ({len(templates)})",
                        callback_data=f"template_category_{category}"
                    )])
                
                keyboard_buttons.extend([
                    [InlineKeyboardButton(
                        text="📝 Все шаблоны",
                        callback_data="template_category_all"
                    )],
                    [InlineKeyboardButton(
                        text="🔄 Сбросить шаблон по умолчанию",
                        callback_data="reset_default_template"
                    )],
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings"
                    )]
                ])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
                
                await safe_edit_text(callback.message, 
                    "📝 **Шаблон по умолчанию**\n\n"
                    "🤖 **Умный выбор** - ИИ автоматически подберёт подходящий шаблон\n"
                    "📁 **Категории** - выберите конкретный шаблон\n\n"
                    "Выберите режим работы:",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в settings_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")
    
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
            
            # Создаем клавиатуру с категориями
            category_names = {
                'management': '👔 Управленческие',
                'product': '🚀 Продуктовые',
                'technical': '⚙️ Технические',
                'general': '📋 Общие',
                'sales': '💼 Продажи'
            }
            
            keyboard_buttons = []
            
            # Добавляем опцию "Умный выбор" первой
            keyboard_buttons.append([InlineKeyboardButton(
                text="🤖 Умный выбор (рекомендуется)",
                callback_data="quick_template_smart"
            )])
            
            # Добавляем категории
            for category, cat_templates in sorted(categories.items()):
                category_name = category_names.get(category, f'📁 {category.title()}')
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{category_name} ({len(cat_templates)})",
                    callback_data=f"quick_category_{category}"
                )])
            
            # Добавляем кнопку "Все шаблоны"
            keyboard_buttons.append([InlineKeyboardButton(
                text="📝 Все шаблоны",
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
    
    @router.callback_query(F.data == "settings_reset")
    async def settings_reset_callback(callback: CallbackQuery):
        """Обработчик сброса всех настроек"""
        try:
            # Сбрасываем все настройки пользователя
            await user_service.update_user_llm_preference(callback.from_user.id, None)
            # Сбрасываем режим вывода протокола на значение по умолчанию
            try:
                await user_service.update_user_protocol_output_preference(callback.from_user.id, 'messages')
            except Exception:
                pass
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])
            
            await safe_edit_text(callback.message, 
                "🔄 **Настройки сброшены**\n\n"
                "Все ваши настройки восстановлены по умолчанию:\n\n"
                "• Предпочтения ИИ сброшены\n"
                "• Шаблон по умолчанию сброшен\n"
                "• Другие настройки восстановлены\n\n"
                "Теперь бот будет использовать настройки по умолчанию.",
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в settings_reset_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе настроек")

    @router.callback_query(F.data == "settings_protocol_output")
    async def settings_protocol_output_callback(callback: CallbackQuery):
        """Обработчик настройки режима вывода протокола"""
        try:
            # Получаем текущую настройку пользователя
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            current = getattr(user, 'protocol_output_mode', None) or 'messages'

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current == 'messages' else ''}💬 В сообщения",
                    callback_data="set_protocol_output_messages"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current == 'file' else ''}📎 В файл md",
                    callback_data="set_protocol_output_file"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if current == 'pdf' else ''}📄 В файл pdf",
                    callback_data="set_protocol_output_pdf"
                )],
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])

            await safe_edit_text(callback.message, 
                "📤 **Вывод протокола**\n\n"
                "Выберите, как отправлять готовый протокол:\n"
                "• 💬 В сообщения — протокол приходит текстом в чат (по умолчанию)\n"
                "• 📎 В файл md — протокол отправляется как прикрепленный файл (.md)\n"
                "• 📄 В файл pdf — протокол отправляется как прикрепленный файл (.pdf)",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в settings_protocol_output_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")

    @router.callback_query(F.data.in_({"set_protocol_output_messages", "set_protocol_output_file", "set_protocol_output_pdf"}))
    async def set_protocol_output_mode_callback(callback: CallbackQuery):
        """Установка режима вывода протокола"""
        try:
            if callback.data.endswith('messages'):
                mode = 'messages'
                mode_text = "💬 В сообщения"
            elif callback.data.endswith('pdf'):
                mode = 'pdf'
                mode_text = "📄 В файл pdf"
            else:
                mode = 'file'
                mode_text = "📎 В файл md"
            
            await user_service.update_user_protocol_output_preference(callback.from_user.id, mode)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])

            await safe_edit_text(callback.message, 
                f"✅ Режим вывода протокола изменён на: {mode_text}",
                reply_markup=keyboard
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в set_protocol_output_mode_callback: {e}")
            await callback.answer("❌ Не удалось изменить режим вывода")
    
    @router.callback_query(F.data == "back_to_settings")
    async def back_to_settings_callback(callback: CallbackQuery):
        """Обработчик возврата к главному меню настроек"""
        try:
            from ux.quick_actions import QuickActionsUI
            
            keyboard = QuickActionsUI.create_settings_menu()
            
            await safe_edit_text(callback.message, 
                "⚙️ **Настройки бота**\n\n"
                "Настройте бота под ваши предпочтения:",
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в back_to_settings_callback: {e}")
            await callback.answer("❌ Произошла ошибка при возврате к настройкам")
    
    
    
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
                        "✅ **Установлен режим: Умный выбор**\n\n"
                        "🤖 ИИ будет автоматически подбирать подходящий шаблон "
                        "на основе содержания каждой встречи.\n\n"
                        "📊 Анализируется:\n"
                        "• Тематика встречи\n"
                        "• Ключевые слова\n"
                        "• История использования\n\n"
                        "Это рекомендуемый режим для большинства пользователей.\n\n"
                        "💡 Вы можете в любое время вернуться к конкретному шаблону.",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                else:
                    # Получаем информацию о конкретном шаблоне
                    template = await template_service.get_template_by_id(template_id)
                    
                    await safe_edit_text(callback.message, 
                        f"✅ **Шаблон по умолчанию установлен!**\n\n"
                        f"Теперь шаблон **{template.name}** будет использоваться автоматически "
                        f"при обработке файлов.\n\n"
                        f"Вы можете изменить это в любое время в настройках.",
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
                    "🔄 **Шаблон по умолчанию сброшен**\n\n"
                    "Теперь бот будет спрашивать выбор шаблона при каждой обработке файла.\n\n"
                    "💡 **Рекомендуем:** Установите '🤖 Умный выбор' для автоматического подбора "
                    "подходящего шаблона на основе содержания встречи.\n\n"
                    "Вы можете установить новый шаблон в любое время.",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                await callback.answer()
            else:
                await callback.answer("❌ Не удалось сбросить шаблон по умолчанию")
            
        except Exception as e:
            logger.error(f"Ошибка в reset_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе шаблона")
    
    # Обработчик отмены задачи из очереди
    @router.callback_query(F.data.startswith("cancel_task_"))
    async def cancel_task_handler(callback: CallbackQuery, state: FSMContext):
        """Обработчик отмены задачи"""
        await _cancel_task_callback(callback, state)
    
    # ============================================================================
    # Обработчики для подтверждения сопоставления спикеров
    # ============================================================================
    
    @router.callback_query(F.data.startswith("sm_change:"))
    async def speaker_mapping_change_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик начала изменения сопоставления спикера"""
        try:
            await _safe_callback_answer(callback)
            
            # Парсим данные: sm_change:{speaker_id}:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 3:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return
            
            speaker_id = parts[1]
            user_id_from_callback = int(parts[2])
            
            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return
            
            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)
            
            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                await callback.answer()
                return
            
            speaker_mapping = state_data.get('speaker_mapping', {})
            diarization_data = state_data.get('diarization_data', {})
            participants = state_data.get('participants_list', [])
            
            # Извлекаем speakers_text из кеша если доступен
            transcription_result = state_data.get('transcription_result', {})
            speakers_text = transcription_result.get('speakers_text') if transcription_result else None
            
            # Обновляем сообщение, показывая выбор участников для этого спикера
            from src.ux.speaker_mapping_ui import update_mapping_message
            await update_mapping_message(
                callback.message,
                speaker_mapping,
                diarization_data,
                participants,
                user_id_from_callback,
                current_editing_speaker=speaker_id,
                speakers_text=speakers_text
            )
            
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_change_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")
    
    @router.callback_query(F.data.startswith("sm_select:"))
    async def speaker_mapping_select_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора участника для спикера"""
        try:
            await _safe_callback_answer(callback)
            
            # Парсим данные: sm_select:{speaker_id}:{participant_idx}:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 4:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return
            
            speaker_id = parts[1]
            participant_idx_str = parts[2]
            user_id_from_callback = int(parts[3])
            
            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return
            
            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)
            
            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                await callback.answer()
                return
            
            speaker_mapping = state_data.get('speaker_mapping', {}).copy()
            diarization_data = state_data.get('diarization_data', {})
            participants = state_data.get('participants_list', [])
            
            # Обрабатываем выбор
            if participant_idx_str == "none":
                # Удаляем сопоставление
                speaker_mapping.pop(speaker_id, None)
                await callback.answer("✅ Сопоставление удалено")
            else:
                try:
                    participant_idx = int(participant_idx_str)
                    if 0 <= participant_idx < len(participants):
                        participant_name = participants[participant_idx].get('name', '')
                        if participant_name:
                            # Проверяем, не используется ли уже этот участник другим спикером
                            used_by = None
                            for sid, pname in speaker_mapping.items():
                                if sid != speaker_id and pname == participant_name:
                                    used_by = sid
                                    break
                            
                            if used_by:
                                await callback.answer(
                                    f"⚠️ Этот участник уже сопоставлен с {used_by}",
                                    show_alert=True
                                )
                                return
                            
                            speaker_mapping[speaker_id] = participant_name
                            await callback.answer("✅ Сопоставление изменено")
                        else:
                            await callback.answer("❌ Имя участника не найдено")
                            return
                    else:
                        await callback.answer("❌ Неверный индекс участника")
                        return
                except ValueError:
                    await callback.answer("❌ Неверный формат индекса")
                    return
            
            # Обновляем состояние в кеше
            await mapping_state_cache.update_mapping(user_id_from_callback, speaker_mapping)
            
            # Извлекаем speakers_text из кеша если доступен
            transcription_result = state_data.get('transcription_result', {})
            speakers_text = transcription_result.get('speakers_text') if transcription_result else None
            
            # Обновляем сообщение (возвращаемся к основному виду)
            from src.ux.speaker_mapping_ui import update_mapping_message
            await update_mapping_message(
                callback.message,
                speaker_mapping,
                diarization_data,
                participants,
                user_id_from_callback,
                current_editing_speaker=None,
                speakers_text=speakers_text
            )
            
        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_select_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")
    
    @router.callback_query(F.data.startswith("sm_cancel:"))
    async def speaker_mapping_cancel_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик отмены редактирования (возврат к основному виду)"""
        try:
            await _safe_callback_answer(callback)
            
            # Парсим данные: sm_cancel:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 2:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return
            
            user_id_from_callback = int(parts[1])
            
            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return
            
            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)
            
            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                await callback.answer()
                return
            
            speaker_mapping = state_data.get('speaker_mapping', {})
            diarization_data = state_data.get('diarization_data', {})
            participants = state_data.get('participants_list', [])
            
            # Извлекаем speakers_text из кеша если доступен
            transcription_result = state_data.get('transcription_result', {})
            speakers_text = transcription_result.get('speakers_text') if transcription_result else None
            
            # Возвращаемся к основному виду
            from src.ux.speaker_mapping_ui import update_mapping_message
            await update_mapping_message(
                callback.message,
                speaker_mapping,
                diarization_data,
                participants,
                user_id_from_callback,
                current_editing_speaker=None,
                speakers_text=speakers_text
            )
            
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_cancel_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")
    
    @router.callback_query(F.data.startswith("sm_confirm:"))
    async def speaker_mapping_confirm_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик подтверждения сопоставления и продолжения обработки"""
        try:
            await _safe_callback_answer(callback, "⏳ Продолжаю обработку...")
            
            # Парсим данные: sm_confirm:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 2:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return
            
            user_id_from_callback = int(parts[1])
            
            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return
            
            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)
            
            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                return
            
            speaker_mapping = state_data.get('speaker_mapping', {})
            
            # Обновляем сообщение (кратко, без обещаний - реальная обработка начнется в следующем сообщении)
            await safe_edit_text(
                callback.message,
                "✅ **Сопоставление подтверждено**",
                parse_mode="Markdown"
            )
            
            # Очищаем состояние FSM
            await state.clear()
            
            # Продолжаем обработку
            await processing_service.continue_processing_after_mapping_confirmation(
                user_id=user_id_from_callback,
                confirmed_mapping=speaker_mapping,
                bot=callback.bot,
                chat_id=callback.message.chat.id
            )
            
            # Очищаем кеш состояния
            await mapping_state_cache.clear_state(user_id_from_callback)
            
        except Exception as e:
            # Расширенное логирование ошибки
            import traceback
            import sys
            
            logger.error(f"❌ Ошибка в speaker_mapping_confirm_callback")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
            error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
            logger.error(f"Детали: {error_msg_safe}")
            
            # Логируем контекст callback
            try:
                if 'user_id_from_callback' in locals():
                    logger.error(f"Контекст callback:")
                    logger.error(f"  - User ID: {user_id_from_callback}")
                    logger.error(f"  - Chat ID: {callback.message.chat.id}")
                    logger.error(f"  - Callback data: {callback.data}")
                    
                    # Пытаемся загрузить состояние для дополнительного контекста
                    try:
                        from src.services.mapping_state_cache import mapping_state_cache
                        state_data = await mapping_state_cache.load_state(user_id_from_callback)
                        if state_data:
                            request_data = state_data.get('request_data', {})
                            logger.error(f"  - LLM провайдер: {request_data.get('llm_provider', 'unknown')}")
                            logger.error(f"  - Файл: {request_data.get('file_name', 'unknown')}")
                    except Exception as state_error:
                        logger.warning(f"Не удалось получить дополнительный контекст: {state_error}")
            except Exception as log_error:
                logger.warning(f"Ошибка при логировании контекста: {log_error}")
            
            # Полный traceback - используем несколько методов для гарантированного вывода
            logger.error("Полный traceback:", exc_info=True)
            
            # Дополнительно выводим traceback как строку для надёжности
            tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
            logger.error("Детальный traceback (построчно):")
            for line in tb_lines:
                logger.error(line.rstrip())
            
            # Выводим стек вызовов
            logger.error(f"Стек вызовов: {traceback.format_stack()}")
            
            await safe_edit_text(
                callback.message,
                "❌ Произошла ошибка при продолжении обработки.\n\n"
                "Пожалуйста, попробуйте начать обработку заново."
            )
    
    @router.callback_query(F.data.startswith("sm_skip:"))
    async def speaker_mapping_skip_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик пропуска сопоставления (продолжение без имен)"""
        try:
            await _safe_callback_answer(callback, "⏳ Продолжаю обработку без сопоставления...")
            
            # Парсим данные: sm_skip:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 2:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return
            
            user_id_from_callback = int(parts[1])
            
            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return
            
            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)
            
            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                return
            
            # Продолжаем с пустым mapping
            empty_mapping = {}
            
            # Обновляем сообщение
            await safe_edit_text(
                callback.message,
                "⏭️ **Сопоставление пропущено**\n\n"
                "⏳ Продолжаю генерацию протокола без замены имен спикеров...",
                parse_mode="Markdown"
            )
            
            # Очищаем состояние FSM
            await state.clear()
            
            # Продолжаем обработку с пустым mapping
            await processing_service.continue_processing_after_mapping_confirmation(
                user_id=user_id_from_callback,
                confirmed_mapping=empty_mapping,
                bot=callback.bot,
                chat_id=callback.message.chat.id
            )
            
            # Очищаем кеш состояния
            await mapping_state_cache.clear_state(user_id_from_callback)
            
        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_skip_callback: {e}", exc_info=True)
            await safe_edit_text(
                callback.message,
                "❌ Произошла ошибка при продолжении обработки.\n\n"
                "Пожалуйста, попробуйте начать обработку заново."
            )
    
    return router


async def _show_llm_selection(callback: CallbackQuery, state: FSMContext, 
                             user_service: UserService, llm_service: EnhancedLLMService,
                             processing_service: ProcessingService):
    """Показать выбор LLM или использовать сохранённые предпочтения"""
    user = await user_service.get_user_by_telegram_id(callback.from_user.id)
    available_providers = llm_service.get_available_providers()
    
    if not available_providers:
        await safe_edit_text(callback.message, 
            "❌ Нет доступных LLM провайдеров. "
            "Проверьте конфигурацию API ключей."
        )
        return
    
    # Проверяем, есть ли у пользователя сохранённые предпочтения
    if user and user.preferred_llm is not None:
        preferred_llm = user.preferred_llm
        # Проверяем, что предпочитаемый LLM доступен
        if preferred_llm in available_providers:
            # Сохраняем в состояние и сразу переходим к обработке
            await state.update_data(llm_provider=preferred_llm)
            # Определяем отображаемое имя: для OpenAI используем название модели, без префикса провайдера
            llm_display = available_providers[preferred_llm]
            if preferred_llm == 'openai':
                try:
                    from config import settings as app_settings
                    selected_key = getattr(user, 'preferred_openai_model_key', None)
                    preset = None
                    if selected_key:
                        preset = next((p for p in getattr(app_settings, 'openai_models', []) if p.key == selected_key), None)
                    if not preset:
                        models = getattr(app_settings, 'openai_models', [])
                        if models:
                            preset = models[0]
                    if preset and getattr(preset, 'name', None):
                        llm_display = preset.name
                except Exception:
                    pass
            await safe_edit_text(callback.message, 
                f"🤖 Используется LLM: {llm_display}\n\n"
                "⏳ Начинаю обработку..."
            )
            # Отвечаем на callback перед длительной обработкой
            await _safe_callback_answer(callback)
            await _process_file(callback, state, processing_service)
            return
    
    # Если предпочтений нет или предпочитаемый LLM недоступен, показываем выбор
    current_llm = user.preferred_llm if user else 'openai'
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅ ' if provider_key == current_llm else ''}{provider_name}",
            callback_data=f"select_llm_{provider_key}"
        )]
        for provider_key, provider_name in available_providers.items()
    ])
    
    await safe_edit_text(callback.message, 
        "🤖 Выберите LLM для обработки:",
        reply_markup=keyboard
    )


async def _process_file(callback: CallbackQuery, state: FSMContext, processing_service: ProcessingService):
    """Начать обработку файла"""
    from src.models.processing import ProcessingRequest
    from src.services.task_queue_manager import task_queue_manager
    from src.models.task_queue import TaskPriority
    from src.ux.queue_tracker import QueueTrackerFactory
    import asyncio
    
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        
        # ДОБАВЛЕНО: Логирование данных из state для диагностики
        logger.info(f"🔍 Данные из state перед созданием request (callback):")
        participants_list = data.get('participants_list')
        if participants_list:
            logger.info(f"  participants_list: {len(participants_list)} чел.")
            # Показываем первые 3 участника для проверки
            for i, p in enumerate(participants_list[:3], 1):
                logger.info(f"    {i}. {p.get('name')} ({p.get('role', 'без роли')})")
            if len(participants_list) > 3:
                logger.info(f"    ... и еще {len(participants_list) - 3} участников")
        else:
            logger.warning("  participants_list: None (НЕ ПЕРЕДАН!)")
        logger.info(f"  meeting_topic: {data.get('meeting_topic')}")
        logger.info(f"  meeting_date: {data.get('meeting_date')}")
        logger.info(f"  meeting_time: {data.get('meeting_time')}")
        protocol_info = (data.get('protocol_info') or {})
        logger.info(f"  meeting_agenda set: {bool(protocol_info.get('meeting_agenda'))}")
        logger.info(f"  project_list set: {bool(protocol_info.get('project_list'))}")
        
        # Проверяем наличие LLM (template_id может быть None для умного выбора)
        if not data.get('llm_provider'):
            await safe_edit_text(callback.message, 
                "❌ Ошибка: не выбран LLM провайдер. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return
        
        # Проверяем template_id только если не используется умный выбор
        if (not data.get('use_smart_selection') and 
            not data.get('template_id')):
            await safe_edit_text(callback.message, 
                "❌ Ошибка: не выбран шаблон. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return
        
        # Проверяем, что есть либо file_id (для Telegram файлов), либо file_path (для внешних файлов)
        is_external_file = data.get('is_external_file', False)
        if is_external_file:
            if not data.get('file_path') or not data.get('file_name'):
                await safe_edit_text(callback.message, 
                    "❌ Ошибка: отсутствуют данные о внешнем файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return
        else:
            if not data.get('file_id') or not data.get('file_name'):
                await safe_edit_text(callback.message, 
                    "❌ Ошибка: отсутствуют данные о файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return
        
        # Создаем запрос на обработку
        request = ProcessingRequest(
            file_id=data.get('file_id') if not is_external_file else None,
            file_path=data.get('file_path') if is_external_file else None,
            file_name=data['file_name'],
            file_url=data.get('file_url'),  # Оригинальный URL для внешних файлов
            template_id=data['template_id'],
            llm_provider=data['llm_provider'],
            user_id=callback.from_user.id,
            language="ru",
            is_external_file=is_external_file,
            # ДОБАВЛЕНО: Передача участников и информации о встрече
            participants_list=data.get('participants_list'),
            meeting_topic=data.get('meeting_topic'),
            meeting_date=data.get('meeting_date'),
            meeting_time=data.get('meeting_time'),
            meeting_agenda=protocol_info.get('meeting_agenda'),
            project_list=protocol_info.get('project_list')
        )
        
        # ДОБАВЛЕНО: Логирование ProcessingRequest сразу после создания
        logger.info(f"🔍 ProcessingRequest создан, проверка полей:")
        if request.participants_list:
            logger.info(f"  request.participants_list: {len(request.participants_list)} чел.")
        else:
            logger.warning(f"  request.participants_list: None (НЕ ПОПАЛ В REQUEST!)")
        logger.info(f"  request.meeting_topic: {request.meeting_topic}")
        logger.info(f"  request.meeting_date: {request.meeting_date}")
        logger.info(f"  request.meeting_time: {request.meeting_time}")
        
        # Добавляем задачу в очередь
        queued_task = await task_queue_manager.add_task(
            request=request,
            chat_id=callback.message.chat.id,
            priority=TaskPriority.NORMAL
        )
        
        # Удаляем старое сообщение с выбором
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        # Получаем позицию в очереди
        position = await task_queue_manager.get_queue_position(str(queued_task.task_id))
        total_in_queue = await task_queue_manager.get_queue_size()
        
        # Создаем трекер позиции в очереди
        queue_tracker = await QueueTrackerFactory.create_tracker(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            task_id=str(queued_task.task_id),
            initial_position=position if position is not None else 0,
            total_in_queue=total_in_queue
        )
        
        # Сохраняем message_id в задаче
        if queue_tracker.message_id:
            queued_task.message_id = queue_tracker.message_id
            from database import db
            await db.update_queue_task_message_id(str(queued_task.task_id), queue_tracker.message_id)
        
        # Запускаем фоновое обновление позиции в очереди
        from src.handlers.message_handlers import _monitor_queue_position
        asyncio.create_task(_monitor_queue_position(
            queue_tracker, queued_task.task_id, task_queue_manager
        ))
        
        # Очищаем состояние
        await state.clear()
        
        logger.info(f"Задача {queued_task.task_id} успешно добавлена в очередь через callback")
            
    except Exception as e:
        logger.error(f"Ошибка при создании запроса на обработку: {e}")
        await safe_edit_text(callback.message, "❌ Произошла ошибка при подготовке обработки файла.")
        await state.clear()


# Обработчик отмены задачи
async def _cancel_task_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены задачи из очереди"""
    from src.services.task_queue_manager import task_queue_manager
    from src.ux.queue_tracker import QueuePositionTracker
    
    try:
        # Извлекаем task_id из callback_data
        task_id = callback.data.replace("cancel_task_", "")
        
        # Отменяем задачу
        success = await task_queue_manager.cancel_task(task_id)
        
        if success:
            # Обновляем сообщение
            tracker = QueuePositionTracker(callback.bot, callback.message.chat.id, task_id)
            tracker.message_id = callback.message.message_id
            await tracker.show_cancelled()
            
            logger.info(f"Задача {task_id} отменена пользователем {callback.from_user.id}")
        else:
            # Задача не найдена или уже обрабатывается
            await callback.answer(
                "Задача уже начала обрабатываться и не может быть отменена",
                show_alert=True
            )
            
    except Exception as e:
        logger.error(f"Ошибка при отмене задачи: {e}")
        await callback.answer("Ошибка при отмене задачи", show_alert=True)


# Старый код функции _process_file - удалено
# Теперь обработка происходит через очередь задач


def _fix_markdown_tags(text: str) -> str:
    """Исправить незакрытые Markdown-теги в тексте"""
    # Подсчитываем количество открытых/закрытых тегов
    bold_count = text.count('**')
    italic_count = text.count('_')
    code_count = text.count('`')
    
    # Закрываем незакрытые теги
    if bold_count % 2 != 0:
        text = text + '**'
    if italic_count % 2 != 0:
        text = text + '_'
    if code_count % 2 != 0:
        text = text + '`'
    
    return text


async def _send_long_message(chat_id: int, text: str, bot, max_length: int = 4096):
    """Отправить длинное сообщение по частям"""
    # Учитываем заголовок при расчете максимальной длины части
    header_template = "📄 **Протокол встречи** (часть {}/{})\n\n"
    max_header_length = len(header_template.format(999, 999))  # Максимальная длина заголовка
    max_part_length = max_length - max_header_length
    
    if len(text) <= max_length:
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown")
            return
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            # Если не удалось отправить с Markdown, пробуем без него
            await bot.send_message(chat_id, text)
            return
    
    # Разбиваем текст на части
    parts = []
    current_part = ""
    
    for line in text.split('\n'):
        if len(current_part) + len(line) + 1 <= max_part_length:
            current_part += line + '\n'
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = line + '\n'
    
    if current_part:
        parts.append(current_part.strip())
    
    # Отправляем части с обработкой ошибок
    for i, part in enumerate(parts):
        try:
            header = f"📄 **Протокол встречи** (часть {i+1}/{len(parts)})\n\n"
            full_message = header + part
            
            # Исправляем незакрытые Markdown-теги
            full_message = _fix_markdown_tags(full_message)
            
            # Проверяем, что сообщение не превышает лимит
            if len(full_message) > max_length:
                # Если превышает, отправляем без Markdown
                await bot.send_message(chat_id, full_message)
            else:
                await bot.send_message(chat_id, full_message, parse_mode="Markdown")
                
        except Exception as e:
            logger.error(f"Ошибка отправки части {i+1}: {e}")
            # Пробуем отправить без Markdown
            try:
                header = f"📄 Протокол встречи (часть {i+1}/{len(parts)})\n\n"
                await bot.send_message(chat_id, header + part)
            except Exception as e2:
                logger.error(f"Критическая ошибка отправки части {i+1}: {e2}")
                # Отправляем простой текст без заголовка
                await bot.send_message(chat_id, part[:max_length])


