"""
Обработчики callback запросов
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, OptimizedProcessingService
from src.utils.pdf_converter import convert_markdown_to_pdf


async def _safe_callback_answer(callback: CallbackQuery, text: str = None):
    """Безопасный ответ на callback query с обработкой устаревших запросов"""
    try:
        await callback.answer(text=text)
    except Exception as e:
        error_str = str(e).lower()
        if "query is too old" in error_str or "query id is invalid" in error_str:
            logger.debug(f"Callback query устарел: {e}")
        else:
            logger.warning(f"Ошибка ответа на callback: {e}")


def setup_callback_handlers(user_service: UserService, template_service: TemplateService,
                           llm_service: EnhancedLLMService, processing_service: OptimizedProcessingService) -> Router:
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
                "🔄 Предпочтения LLM сброшены.\n\n"
                "Теперь бот будет спрашивать выбор LLM при каждой обработке файла."
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в reset_llm_preference_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе настроек")
    
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
                await callback.message.edit_text("❌ Шаблоны не найдены. Обратитесь к администратору.")
                return
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'⭐ ' if t.is_default else ''}{t.name}",
                    callback_data=f"select_template_{t.id}"
                )]
                for t in templates
            ])
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
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
            await callback.message.edit_text(
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

                await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
                await callback.message.edit_text(
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

            await callback.message.edit_text(
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
            await callback.message.edit_text(
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
            await callback.message.edit_text(
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
                
                await callback.message.edit_text(
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
                    'technical': '⚙️ Технические',
                    'general': '📋 Общие',
                    'sales': '💼 Продажи'
                }
                
                keyboard_buttons = []
                
                # ПЕРВАЯ кнопка - Умный выбор (рекомендуется)
                keyboard_buttons.append([InlineKeyboardButton(
                    text="🤖 Умный выбор (рекомендуется)",
                    callback_data="set_default_template_0"  # 0 = умный выбор
                )])
                
                # Категории шаблонов
                for category, templates in sorted(categories.items()):
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
                
                await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
                await callback.message.edit_text(
                    "❌ **Ошибка**\n\n"
                    "У вас не установлен шаблон по умолчанию.",
                    parse_mode="Markdown"
                )
                return
            
            # Если сохранён умный выбор (template_id = 0)
            if user.default_template_id == 0:
                await state.update_data(template_id=0, use_smart_selection=True)
                await callback.message.edit_text(
                    "🤖 **Используется Умный выбор шаблона**\n\n"
                    "ИИ автоматически подберёт подходящий шаблон после транскрипции.\n\n"
                    "⏳ Переходим к выбору ИИ для обработки...",
                    parse_mode="Markdown"
                )
            else:
                # Используем конкретный шаблон
                template = await template_service.get_template_by_id(user.default_template_id)
                if not template:
                    await callback.message.edit_text(
                        "❌ **Ошибка**\n\n"
                        "Сохранённый шаблон не найден.",
                        parse_mode="Markdown"
                    )
                    return
                
                await state.update_data(template_id=template.id, use_smart_selection=False)
                await callback.message.edit_text(
                    f"📋 **Используется шаблон: {template.name}**\n\n"
                    "⏳ Переходим к выбору ИИ для обработки...",
                    parse_mode="Markdown"
                )
            
            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)
            
        except Exception as e:
            logger.error(f"Ошибка в use_saved_default_callback: {e}")
            await _safe_callback_answer(callback, "❌ Произошла ошибка при использовании шаблона")
    
    @router.callback_query(F.data == "quick_set_default")
    async def quick_set_default_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик быстрой установки шаблона по умолчанию"""
        try:
            # Немедленно отвечаем на callback query
            await _safe_callback_answer(callback)
            
            # Получаем все шаблоны
            templates = await template_service.get_all_templates()
            
            if not templates:
                await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
                
                await callback.message.edit_text(
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
                    await callback.message.edit_text(
                        "❌ **Ошибка**\n\n"
                        "Шаблон не найден.",
                        parse_mode="Markdown"
                    )
                    return
                
                # Сохраняем шаблон как по умолчанию
                await template_service.set_user_default_template(callback.from_user.id, template_id)
                await state.update_data(template_id=template_id, use_smart_selection=False)
                
                await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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

            await callback.message.edit_text(
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

            await callback.message.edit_text(
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
            
            await callback.message.edit_text(
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
                    await callback.message.edit_text(
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
                    
                    await callback.message.edit_text(
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
                
                await callback.message.edit_text(
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
                
                await callback.message.edit_text(
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
    
    return router


async def _show_llm_selection(callback: CallbackQuery, state: FSMContext, 
                             user_service: UserService, llm_service: EnhancedLLMService,
                             processing_service: OptimizedProcessingService):
    """Показать выбор LLM или использовать сохранённые предпочтения"""
    user = await user_service.get_user_by_telegram_id(callback.from_user.id)
    available_providers = llm_service.get_available_providers()
    
    if not available_providers:
        await callback.message.edit_text(
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
            await callback.message.edit_text(
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
    
    await callback.message.edit_text(
        "🤖 Выберите LLM для обработки:",
        reply_markup=keyboard
    )


async def _process_file(callback: CallbackQuery, state: FSMContext, processing_service: OptimizedProcessingService):
    """Начать обработку файла"""
    from src.models.processing import ProcessingRequest
    from src.services.task_queue_manager import task_queue_manager
    from src.models.task_queue import TaskPriority
    from src.ux.queue_tracker import QueueTrackerFactory
    import asyncio
    
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        
        # Проверяем наличие LLM (template_id может быть None для умного выбора)
        if not data.get('llm_provider'):
            await callback.message.edit_text(
                "❌ Ошибка: не выбран LLM провайдер. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return
        
        # Если не используется умный выбор, проверяем наличие template_id
        if not data.get('use_smart_selection') and not data.get('template_id'):
            await callback.message.edit_text(
                "❌ Ошибка: не выбран шаблон. Пожалуйста, повторите процесс."
            )
            await state.clear()
            return
        
        # Проверяем, что есть либо file_id (для Telegram файлов), либо file_path (для внешних файлов)
        is_external_file = data.get('is_external_file', False)
        if is_external_file:
            if not data.get('file_path') or not data.get('file_name'):
                await callback.message.edit_text(
                    "❌ Ошибка: отсутствуют данные о внешнем файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return
        else:
            if not data.get('file_id') or not data.get('file_name'):
                await callback.message.edit_text(
                    "❌ Ошибка: отсутствуют данные о файле. Пожалуйста, повторите процесс."
                )
                await state.clear()
                return
        
        # Создаем запрос на обработку
        request = ProcessingRequest(
            file_id=data.get('file_id') if not is_external_file else None,
            file_path=data.get('file_path') if is_external_file else None,
            file_name=data['file_name'],
            template_id=data['template_id'],
            llm_provider=data['llm_provider'],
            user_id=callback.from_user.id,
            language="ru",
            is_external_file=is_external_file
        )
        
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
        await callback.message.edit_text("❌ Произошла ошибка при подготовке обработки файла.")
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
    
    # ============================================================================
    # Обработчики административного меню
    # ============================================================================
    
    @router.callback_query(F.data == "admin_status")
    async def admin_status_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Статистика системы'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from api.monitoring import monitoring_api
            
            await callback.answer()
            await callback.message.edit_text("🔄 Получаю статистику системы...")
            
            report = monitoring_api.format_status_report()
            await callback.message.edit_text(report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_status_callback: {e}")
            await callback.message.edit_text(f"❌ Ошибка при получении статуса: {e}")
    
    @router.callback_query(F.data == "admin_health")
    async def admin_health_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Проверка здоровья'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from reliability.health_check import health_checker
            
            await callback.answer()
            await callback.message.edit_text("🔍 Выполняю проверку здоровья системы...")
            
            health_results = await health_checker.check_all()
            
            report_lines = ["🏥 **Детальная проверка здоровья**\n"]
            
            for component, result in health_results.items():
                status_emoji = {
                    "healthy": "✅",
                    "degraded": "⚠️",
                    "unhealthy": "❌",
                    "unknown": "❓"
                }.get(result.status.value, "❓")
                
                report_lines.append(f"**{component}:** {status_emoji} {result.status.value}")
                report_lines.append(f"  └ {result.message}")
                
                if result.response_time:
                    report_lines.append(f"  └ Время ответа: {result.response_time:.3f}с")
                
                report_lines.append("")
            
            report = "\n".join(report_lines)
            await callback.message.edit_text(report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_health_callback: {e}")
            await callback.message.edit_text(f"❌ Ошибка при проверке здоровья: {e}")
    
    @router.callback_query(F.data == "admin_performance")
    async def admin_performance_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Производительность'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from performance import (
                performance_cache, metrics_collector, memory_optimizer, task_pool
            )
            
            await callback.answer()
            await callback.message.edit_text("📊 Собираю данные о производительности...")
            
            # Собираем статистику
            cache_stats = performance_cache.get_stats()
            memory_stats = memory_optimizer.get_optimization_stats()
            task_stats = task_pool.get_stats()
            metrics_stats = metrics_collector.get_current_stats()
            
            # Форматируем отчет
            report = (
                "📊 **Статистика производительности**\n\n"
                
                "💾 **Кэш:**\n"
                f"• Hit Rate: {cache_stats['hit_rate_percent']}%\n"
                f"• Память: {cache_stats['memory_usage_mb']}MB "
                f"({cache_stats['memory_usage_percent']}%)\n"
                f"• Записей: {cache_stats['memory_entries']} + {cache_stats['disk_entries']} (диск)\n\n"
                
                "🧠 **Память:**\n"
                f"• Система: {memory_stats['current_memory']['percent']}%\n"
                f"• Процесс: {memory_stats['current_memory']['process_mb']:.1f}MB\n"
                f"• Автооптимизация: {'Вкл' if memory_stats['is_optimizing'] else 'Выкл'}\n\n"
                
                "⚡ **Задачи:**\n"
                f"• Активные: {task_stats['active_tasks']}\n"
                f"• Макс параллельно: {task_stats['max_concurrent']}\n"
                f"• Успешность: {task_stats['success_rate']:.1f}%\n\n"
                
                "📈 **Обработка:**\n"
                f"• Запросов за час: {metrics_stats['processing']['requests_1h']}\n"
                f"• Успешность: {metrics_stats['processing']['success_rate_percent']}%\n"
                f"• Среднее время: {metrics_stats['processing']['avg_duration_seconds']}с\n"
                f"• Эффективность: {metrics_stats['processing']['avg_efficiency_ratio']}\n"
            )
            
            await callback.message.edit_text(report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_performance_callback: {e}")
            await callback.message.edit_text(f"❌ Ошибка при получении статистики: {e}")
    
    @router.callback_query(F.data == "admin_cleanup")
    async def admin_cleanup_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Управление файлами'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from src.services.cleanup_service import cleanup_service
            from config import settings
            
            await callback.answer()
            
            # Получаем статистику
            stats = cleanup_service.get_cleanup_stats()
            
            # Формируем отчет
            report = (
                "📁 **Статистика файлов**\n\n"
                f"📂 Временные файлы: {stats['temp_files']} ({stats['temp_size_mb']:.1f}MB)\n"
                f"🗂️ Кэш файлы: {stats['cache_files']} ({stats['cache_size_mb']:.1f}MB)\n\n"
                f"⏰ Старые временные файлы: {stats['old_temp_files']}\n"
                f"⏰ Старые кэш файлы: {stats['old_cache_files']}\n\n"
                f"⚙️ **Настройки:**\n"
                f"• Интервал очистки: {settings.cleanup_interval_minutes} мин\n"
                f"• Макс. возраст временных файлов: {settings.temp_file_max_age_hours} ч\n"
                f"• Макс. возраст кэш файлов: {settings.cache_max_age_hours} ч\n"
                f"• Автоочистка: {'✅' if settings.enable_cleanup else '❌'}\n\n"
                "Используйте команду /cleanup_force для принудительной очистки"
            )
            
            await callback.message.edit_text(report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_cleanup_callback: {e}")
            await callback.message.edit_text(f"❌ Ошибка при получении статистики: {e}")
    
    @router.callback_query(F.data == "admin_transcription")
    async def admin_transcription_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Режим транскрипции'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            from config import settings
            
            await callback.answer()
            
            # Создаем клавиатуру для выбора режима
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'local' else ''}🏠 Локальная (Whisper)",
                    callback_data="set_transcription_mode_local"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'cloud' else ''}☁️ Облачная (Groq)",
                    callback_data="set_transcription_mode_cloud"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'hybrid' else ''}🔄 Гибридная (Groq + диаризация)",
                    callback_data="set_transcription_mode_hybrid"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'speechmatics' else ''}🎯 Speechmatics",
                    callback_data="set_transcription_mode_speechmatics"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'deepgram' else ''}🎤 Deepgram",
                    callback_data="set_transcription_mode_deepgram"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'leopard' else ''}🐆 Leopard (Picovoice)",
                    callback_data="set_transcription_mode_leopard"
                )]
            ])
            
            current_mode = settings.transcription_mode
            mode_descriptions = {
                "local": "Локальная транскрипция через Whisper",
                "cloud": "Облачная транскрипция через Groq API",
                "hybrid": "Гибридная: облачная транскрипция + локальная диаризация",
                "speechmatics": "Транскрипция и диаризация через Speechmatics API",
                "deepgram": "Транскрипция и диаризация через Deepgram API",
                "leopard": "Локальная транскрипция через Picovoice Leopard"
            }
            
            current_description = mode_descriptions.get(current_mode, "Неизвестный режим")
            
            await callback.message.edit_text(
                f"🎙️ **Текущий режим транскрипции:** {current_mode}\n"
                f"📝 **Описание:** {current_description}\n\n"
                f"Выберите новый режим:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка в admin_transcription_callback: {e}")
            await callback.message.edit_text(f"❌ Ошибка при получении режимов транскрипции: {e}")
    
    @router.callback_query(F.data == "admin_reset")
    async def admin_reset_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Сброс компонентов'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from reliability.health_check import health_checker
            
            await callback.answer()
            await callback.message.edit_text("🔄 Сбрасываю компоненты надежности...")
            
            # Сбрасываем компоненты
            await llm_service.reset_reliability_components()
            await processing_service.reset_reliability_components()
            
            # Сбрасываем health checker
            for name, cb in health_checker.component_health.items():
                cb.consecutive_failures = 0
                cb.status = health_checker.HealthStatus.UNKNOWN
            
            await callback.message.edit_text("✅ Компоненты надежности сброшены успешно.")
        except Exception as e:
            logger.error(f"Ошибка в admin_reset_callback: {e}")
            await callback.message.edit_text(f"❌ Ошибка при сбросе: {e}")
    
    @router.callback_query(F.data == "admin_export")
    async def admin_export_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Экспорт статистики'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from api.monitoring import monitoring_api
            import tempfile
            import os
            from aiogram.types import FSInputFile, BufferedInputFile
            
            await callback.answer()
            await callback.message.edit_text("📥 Экспортирую статистику...")
            
            # Экспортируем статистику
            json_stats = monitoring_api.export_stats_json()
            
            # Отправляем как файл
            file_input = BufferedInputFile(
                json_stats.encode('utf-8'),
                filename="bot_stats.json"
            )
            
            await callback.message.answer_document(
                file_input,
                caption="📊 Экспорт статистики системы"
            )
            
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка в admin_export_callback: {e}")
            await callback.message.edit_text(f"❌ Ошибка при экспорте: {e}")
    
    @router.callback_query(F.data == "admin_help")
    async def admin_help_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Справка'"""
        from src.utils.admin_utils import is_admin
        
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        await callback.answer()
        
        help_text = """
🔧 **Административные команды**

**Мониторинг:**
• `/status` - общий статус системы
• `/health` - детальная проверка здоровья
• `/stats` - детальная статистика
• `/export_stats` - экспорт статистики в JSON

**Производительность:**
• `/performance` - статистика производительности
• `/optimize` - принудительная оптимизация памяти

**Управление:**
• `/reset_reliability` - сброс компонентов надежности
• `/transcription_mode` - переключение режима транскрипции

**Очистка файлов:**
• `/cleanup` - статистика файлов и настройки очистки
• `/cleanup_force` - принудительная очистка всех временных файлов

**Справка:**
• `/admin_help` - эта справка

**Примечание:** Административные команды доступны только авторизованным пользователям.
        """
        
        await callback.message.edit_text(help_text, parse_mode="Markdown")


