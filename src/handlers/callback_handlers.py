"""
Обработчики callback запросов
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, OptimizedProcessingService


def _convert_markdown_to_pdf(markdown_text: str, output_path: str) -> None:
    """
    Конвертирует markdown текст в PDF файл с поддержкой кириллицы
    
    Args:
        markdown_text: текст в формате markdown
        output_path: путь к выходному PDF файлу
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import re
    import os
    
    # Регистрируем шрифты с поддержкой кириллицы
    # Ищем системные шрифты
    font_registered = False
    
    # Попробуем найти и зарегистрировать системные шрифты для macOS
    possible_fonts = [
        # macOS
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        # Linux
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    
    for font_path in possible_fonts:
        if os.path.exists(font_path):
            try:
                if font_path.endswith('.ttc'):
                    # TrueType Collection - используем первый шрифт
                    pdfmetrics.registerFont(TTFont('CustomFont', font_path, subfontIndex=0))
                    pdfmetrics.registerFont(TTFont('CustomFont-Bold', font_path, subfontIndex=1))
                else:
                    pdfmetrics.registerFont(TTFont('CustomFont', font_path))
                    pdfmetrics.registerFont(TTFont('CustomFont-Bold', font_path))
                font_registered = True
                break
            except Exception:
                continue
    
    # Если не нашли системный шрифт, используем стандартный Helvetica
    font_name = 'CustomFont' if font_registered else 'Helvetica'
    font_name_bold = 'CustomFont-Bold' if font_registered else 'Helvetica-Bold'
    
    # Создаем PDF документ
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # Стили с кастомными шрифтами
    styles = getSampleStyleSheet()
    
    # Кастомные стили с поддержкой кириллицы
    styles.add(ParagraphStyle(
        name='CustomTitle',
        fontName=font_name_bold,
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        spaceBefore=12,
        leading=28
    ))
    
    styles.add(ParagraphStyle(
        name='CustomHeading2',
        fontName=font_name_bold,
        fontSize=18,
        textColor=colors.HexColor('#34495e'),
        spaceAfter=10,
        spaceBefore=10,
        leading=22
    ))
    
    styles.add(ParagraphStyle(
        name='CustomHeading3',
        fontName=font_name_bold,
        fontSize=14,
        textColor=colors.HexColor('#7f8c8d'),
        spaceAfter=8,
        spaceBefore=8,
        leading=18
    ))
    
    styles.add(ParagraphStyle(
        name='CustomBody',
        fontName=font_name,
        fontSize=12,
        leading=16,
        alignment=TA_LEFT
    ))
    
    # Парсинг markdown и создание элементов
    story = []
    lines = markdown_text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Пропускаем пустые строки
        if not line:
            story.append(Spacer(1, 0.3*cm))
            i += 1
            continue
        
        # Заголовки
        if line.startswith('# '):
            text = line[2:].strip()
            story.append(Paragraph(text, styles['CustomTitle']))
        elif line.startswith('## '):
            text = line[3:].strip()
            story.append(Paragraph(text, styles['CustomHeading2']))
        elif line.startswith('### '):
            text = line[4:].strip()
            story.append(Paragraph(text, styles['CustomHeading3']))
        
        # Списки
        elif line.startswith('- ') or line.startswith('* '):
            text = '• ' + line[2:].strip()
            # Обрабатываем жирный текст в списках
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['CustomBody']))
        elif re.match(r'^\d+\.\s', line):
            text = line
            # Обрабатываем жирный текст в нумерованных списках
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['CustomBody']))
        
        # Обычный текст
        else:
            # Обрабатываем жирный текст **text**
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            # Обрабатываем курсив *text*
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['CustomBody']))
        
        i += 1
    
    # Генерируем PDF
    doc.build(story)


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

            # Определяем красивое имя модели для отображения (если доступно)
            llm_model_name = result.llm_provider_used
            try:
                if result.llm_provider_used == 'openai':
                    from config import settings as app_settings
                    from src.services.user_service import UserService
                    user_service = UserService()
                    user = await user_service.get_user_by_telegram_id(callback.from_user.id)
                    selected_key = getattr(user, 'preferred_openai_model_key', None) if user else None
                    preset = None
                    if selected_key:
                        preset = next((p for p in getattr(app_settings, 'openai_models', []) if p.key == selected_key), None)
                    if not preset:
                        models = getattr(app_settings, 'openai_models', [])
                        if models:
                            preset = models[0]
                    if preset:
                        llm_model_name = preset.name
            except Exception:
                # В случае ошибок оставляем провайдера как значение по умолчанию
                pass

            # Показываем результат с улучшенным форматированием
            result_dict = {
                "template_used": {"name": result.template_used.get('name', 'Неизвестный')},
                "llm_provider_used": result.llm_provider_used,
                "llm_model_name": llm_model_name,
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
            
            # Отправляем протокол согласно настройке пользователя
            try:
                from src.services.user_service import UserService as _US
                user_pref_service = _US()
                user = await user_pref_service.get_user_by_telegram_id(callback.from_user.id)
                output_mode = getattr(user, 'protocol_output_mode', None) or 'messages'

                if output_mode in ('file', 'pdf'):
                    # Сохраняем протокол во временный файл и отправляем как документ
                    import tempfile
                    from aiogram.types import FSInputFile
                    import os
                    
                    suffix = '.pdf' if output_mode == 'pdf' else '.md'
                    safe_name = 'protocol'
                    try:
                        # Попробуем извлечь базовое имя из исходного файла
                        data = await state.get_data()
                        original = data.get('file_name') or 'protocol'
                        safe_name = os.path.splitext(os.path.basename(original))[0][:40] or 'protocol'
                    except Exception:
                        pass
                    
                    if output_mode == 'pdf':
                        # Генерируем PDF
                        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                            temp_path = f.name
                        try:
                            _convert_markdown_to_pdf(result.protocol_text or '', temp_path)
                            file_input = FSInputFile(temp_path, filename=f"{safe_name}.pdf")
                            await callback.message.answer_document(
                                file_input,
                                caption="📄 Протокол встречи (PDF)"
                            )
                        finally:
                            try:
                                os.unlink(temp_path)
                            except Exception:
                                pass
                    else:
                        # Сохраняем как MD файл
                        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as f:
                            f.write(result.protocol_text or '')
                            temp_path = f.name
                        try:
                            file_input = FSInputFile(temp_path, filename=f"{safe_name}.md")
                            await callback.message.answer_document(
                                file_input,
                                caption="📎 Протокол встречи (Markdown)"
                            )
                        finally:
                            try:
                                os.unlink(temp_path)
                            except Exception:
                                pass
                else:
                    # По умолчанию отправляем в сообщения (разбиваем по частям при необходимости)
                    await _send_long_message(callback.message.chat.id, result.protocol_text, callback.bot)
            except Exception as e:
                logger.error(f"Ошибка отправки протокола: {e}")
                # Отправляем уведомление об ошибке
                await callback.bot.send_message(
                    callback.message.chat.id,
                    "⚠️ Не удалось отправить протокол. Попробуйте позже."
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
