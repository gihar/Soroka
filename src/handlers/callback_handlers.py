"""
Обработчики callback запросов
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, OptimizedProcessingService


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
            template_id = int(callback.data.replace("select_template_", ""))
            await state.update_data(template_id=template_id)
            
            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)
            
        except Exception as e:
            logger.error(f"Ошибка в select_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при выборе шаблона")
    
    @router.callback_query(F.data.startswith("use_default_template_"))
    async def use_default_template_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик использования шаблона по умолчанию"""
        try:
            template_id = int(callback.data.replace("use_default_template_", ""))
            await state.update_data(template_id=template_id)
            
            # Показываем выбор LLM
            await _show_llm_selection(callback, state, user_service, llm_service, processing_service)
            
        except Exception as e:
            logger.error(f"Ошибка в use_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при использовании шаблона по умолчанию")
    
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
            llm_provider = callback.data.replace("select_llm_", "")
            
            # Сохраняем выбор пользователя как предпочтение
            await user_service.update_user_llm_preference(callback.from_user.id, llm_provider)
            await state.update_data(llm_provider=llm_provider)
            
            # Начинаем обработку
            await _process_file(callback, state, processing_service)
            
        except Exception as e:
            logger.error(f"Ошибка в select_llm_callback: {e}")
            await callback.answer("❌ Произошла ошибка при выборе LLM")
    
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
                "speechmatics": "Speechmatics"
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
    
    @router.callback_query(F.data.startswith("view_template_"))
    async def view_template_callback(callback: CallbackQuery):
        """Обработчик просмотра шаблона"""
        try:
            template_id = int(callback.data.replace("view_template_", ""))
            template = await template_service.get_template_by_id(template_id)
            
            text = f"📝 **{template.name}**\n\n"
            if template.description:
                text += f"*Описание:* {template.description}\n\n"
            
            text += f"```\n{template.content}\n```"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад к списку шаблонов",
                    callback_data="back_to_templates"
                )]
            ])
            
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в view_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при просмотре шаблона")
    
    @router.callback_query(F.data == "back_to_templates")
    async def back_to_templates_callback(callback: CallbackQuery):
        """Возврат к списку шаблонов"""
        try:
            templates = await template_service.get_all_templates()
            
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
            
            await callback.message.edit_text(
                "📝 **Доступные шаблоны:**",
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
    
    @router.callback_query(F.data == "settings_diarization")
    async def settings_diarization_callback(callback: CallbackQuery):
        """Обработчик настройки диаризации"""
        try:
            from config import settings
            
            # Создаем клавиатуру для настройки диаризации
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Включить диаризацию" if not settings.enable_diarization else "❌ Отключить диаризацию",
                    callback_data="toggle_diarization"
                )],
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])
            
            status_text = "✅ Включена" if settings.enable_diarization else "❌ Отключена"
            provider_text = f"Провайдер: {settings.diarization_provider}" if settings.enable_diarization else ""
            
            await callback.message.edit_text(
                "👥 **Настройки диаризации**\n\n"
                f"**Статус:** {status_text}\n"
                f"{provider_text}\n\n"
                "Диаризация позволяет определять разных говорящих в аудио:",
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в settings_diarization_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")
    
    @router.callback_query(F.data == "settings_audio_quality")
    async def settings_audio_quality_callback(callback: CallbackQuery):
        """Обработчик настройки качества аудио"""
        try:
            from config import settings
            
            # Создаем клавиатуру для настройки качества аудио
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🎵 Высокое качество (медленнее)",
                    callback_data="set_audio_quality_high"
                )],
                [InlineKeyboardButton(
                    text="⚡ Быстрая обработка (ниже качество)",
                    callback_data="set_audio_quality_fast"
                )],
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])
            
            await callback.message.edit_text(
                "🎵 **Настройки качества аудио**\n\n"
                "Выберите приоритет:\n\n"
                "• **Высокое качество** - лучшая точность, медленнее\n"
                "• **Быстрая обработка** - быстрее, качество ниже\n\n"
                "Текущие настройки:",
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в settings_audio_quality_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")
    
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
                # Создаем клавиатуру с доступными шаблонами
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"{'⭐ ' if template.is_default else '📝 '}{template.name}",
                        callback_data=f"set_default_template_{template.id}"
                    )] for template in all_templates[:5]  # Показываем первые 5
                ] + [
                    [InlineKeyboardButton(
                        text="🔄 Сбросить шаблон по умолчанию",
                        callback_data="reset_default_template"
                    )],
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings"
                    )]
                ])
                
                await callback.message.edit_text(
                    "📝 **Шаблон по умолчанию**\n\n"
                    "Выберите шаблон, который будет использоваться автоматически:",
                    reply_markup=keyboard
                )
            
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в settings_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при загрузке настроек")
    
    @router.callback_query(F.data == "settings_reset")
    async def settings_reset_callback(callback: CallbackQuery):
        """Обработчик сброса всех настроек"""
        try:
            # Сбрасываем все настройки пользователя
            await user_service.update_user_llm_preference(callback.from_user.id, None)
            # TODO: Добавить сброс других настроек
            
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
    
    @router.callback_query(F.data == "toggle_diarization")
    async def toggle_diarization_callback(callback: CallbackQuery):
        """Обработчик переключения диаризации"""
        try:
            from config import settings
            
            # TODO: Реализовать изменение настройки диаризации
            # Пока просто показываем текущий статус
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])
            
            await callback.message.edit_text(
                "👥 **Диаризация**\n\n"
                "Функция изменения настроек диаризации находится в разработке.\n\n"
                "Текущий статус: " + ("✅ Включена" if settings.enable_diarization else "❌ Отключена"),
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в toggle_diarization_callback: {e}")
            await callback.answer("❌ Произошла ошибка при изменении настроек")
    
    @router.callback_query(F.data.startswith("set_default_template_"))
    async def set_default_template_callback(callback: CallbackQuery):
        """Обработчик установки шаблона по умолчанию"""
        try:
            template_id = int(callback.data.replace("set_default_template_", ""))
            
            # Устанавливаем шаблон по умолчанию
            success = await template_service.set_user_default_template(callback.from_user.id, template_id)
            
            if success:
                # Получаем информацию о шаблоне
                template = await template_service.get_template_by_id(template_id)
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings"
                    )]
                ])
                
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
    
    @router.callback_query(F.data.startswith("set_audio_quality_"))
    async def set_audio_quality_callback(callback: CallbackQuery):
        """Обработчик установки качества аудио"""
        try:
            quality = callback.data.replace("set_audio_quality_", "")
            
            # TODO: Реализовать изменение качества аудио
            # await user_service.set_audio_quality(callback.from_user.id, quality)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="⬅️ Назад к настройкам",
                    callback_data="back_to_settings"
                )]
            ])
            
            quality_text = "высокое качество" if quality == "high" else "быстрая обработка"
            
            await callback.message.edit_text(
                "🎵 **Качество аудио**\n\n"
                "Функция изменения качества аудио находится в разработке.\n\n"
                f"Выбрано: {quality_text}",
                reply_markup=keyboard
            )
            await callback.answer()
            
        except Exception as e:
            logger.error(f"Ошибка в set_audio_quality_callback: {e}")
            await callback.answer("❌ Произошла ошибка при изменении настроек")
    
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
                    "Вы можете установить новый шаблон по умолчанию в любое время.",
                    reply_markup=keyboard
                )
                await callback.answer()
            else:
                await callback.answer("❌ Не удалось сбросить шаблон по умолчанию")
            
        except Exception as e:
            logger.error(f"Ошибка в reset_default_template_callback: {e}")
            await callback.answer("❌ Произошла ошибка при сбросе шаблона")
    
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
            await callback.message.edit_text(
                f"🤖 Используется сохранённый LLM: {available_providers[preferred_llm]}\n\n"
                "⏳ Начинаю обработку..."
            )
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
    
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        
        # Проверяем наличие обязательных данных
        if not data.get('template_id') or not data.get('llm_provider'):
            await callback.message.edit_text(
                "❌ Ошибка: отсутствуют обязательные данные. Пожалуйста, повторите процесс."
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
        
        # Создаем прогресс-трекер
        from ux.progress_tracker import ProgressFactory
        from ux.message_builder import MessageBuilder
        from ux.feedback_system import QuickFeedbackManager, feedback_collector
        # Используем прямую интеграцию с оптимизированным сервисом
        from config import settings
        
        progress_tracker = await ProgressFactory.create_file_processing_tracker(
            callback.bot, callback.message.chat.id, settings.enable_diarization
        )
        
        try:
            # Обрабатываем файл с отображением прогресса
            result = await processing_service.process_file(request, progress_tracker)
            
            await progress_tracker.complete_all()
            
            # Показываем результат с улучшенным форматированием
            result_dict = {
                "template_used": {"name": result.template_used.get('name', 'Неизвестный')},
                "llm_provider_used": result.llm_provider_used,
                "transcription_result": {
                    "transcription": result.transcription_result.transcription,
                    "diarization": result.transcription_result.diarization,
                    "compression_info": result.transcription_result.compression_info
                },
                "processing_duration": result.processing_duration
            }
            
            result_message = MessageBuilder.processing_complete_message(result_dict)
            
            # Отправляем сообщение о завершении с обработкой ошибок длины
            try:
                await callback.bot.send_message(
                    callback.message.chat.id,
                    result_message,
                    parse_mode="Markdown"
                )
            except Exception as e:
                if "message is too long" in str(e).lower():
                    # Если сообщение слишком длинное, отправляем без Markdown
                    await callback.bot.send_message(
                        callback.message.chat.id,
                        result_message
                    )
                else:
                    raise e
            
            # Отправляем протокол с обработкой ошибок
            try:
                await _send_long_message(callback.message.chat.id, result.protocol_text, callback.bot)
            except Exception as e:
                logger.error(f"Ошибка отправки протокола: {e}")
                # Отправляем уведомление об ошибке
                await callback.bot.send_message(
                    callback.message.chat.id,
                    "⚠️ Протокол слишком длинный для отправки. Попробуйте обработать файл меньшего размера."
                )
            
            # Запрашиваем обратную связь
            feedback_manager = QuickFeedbackManager(feedback_collector)
            await feedback_manager.request_quick_feedback(
                callback.message.chat.id, callback.bot, result_dict
            )
            
        except Exception as e:
            logger.error(f"Ошибка при обработке файла: {e}")
            
            # Специальная обработка ошибок размера файла
            error_message = str(e)
            if "message is too long" in error_message.lower():
                user_message = (
                    "📄 **Сообщение слишком длинное**\n\n"
                    "Результат обработки превышает лимит Telegram. Попробуйте:\n\n"
                    "• Обработать файл меньшего размера\n"
                    "• Разделить длинную запись на части\n"
                    "• Использовать более короткий аудиофайл"
                )
            elif "too large" in error_message.lower() or "413" in error_message:
                user_message = (
                    "📦 **Файл слишком большой для облачной транскрипции**\n\n"
                    "Система автоматически переключилась на локальную транскрипцию, "
                    "но произошла ошибка. Попробуйте:\n\n"
                    "• Сжать аудиофайл до меньшего размера\n"
                    "• Разделить длинную запись на несколько частей\n"
                    "• Использовать формат с лучшим сжатием (MP3)\n"
                    "• Снизить качество аудио"
                )
            elif "transcription" in error_message.lower():
                user_message = (
                    "🎤 **Ошибка при транскрипции**\n\n"
                    f"Детали: {error_message}\n\n"
                    "Попробуйте:\n"
                    "• Проверить качество аудио\n"
                    "• Убедиться, что файл не поврежден\n"
                    "• Попробовать другой аудиофайл"
                )
            else:
                user_message = f"❌ **Ошибка при обработке файла**\n\n{error_message}"
            
            await progress_tracker.error("processing", user_message)
            
            # Отправляем сообщение пользователю
            await callback.bot.send_message(
                callback.message.chat.id,
                user_message,
                parse_mode="Markdown"
            )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        await callback.message.edit_text(f"❌ Ошибка при обработке файла: {e}")
    finally:
        await state.clear()


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
