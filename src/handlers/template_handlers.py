"""
Обработчики для работы с шаблонами
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from src.exceptions import TemplateValidationError
from src.models.template import TemplateCreate
from src.services import TemplateService
from src.utils.telegram_safe import safe_answer, safe_edit_text
from src.ux.html_text import esc
from src.ux.message_builder import SOMETHING_WENT_WRONG


class TemplateStates(StatesGroup):
    """Состояния для создания шаблонов"""
    waiting_for_name = State()
    waiting_for_content = State()
    preview_template = State()


def _cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка выхода из создания шаблона — FSM не должен быть ловушкой."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отменить", callback_data="cancel_template_creation")
    ]])


def _looks_like_command(text: str) -> bool:
    return bool(text) and text.lstrip().startswith("/")


def setup_template_handlers(template_service: TemplateService) -> Router:
    """Настройка обработчиков шаблонов"""
    router = Router()
    
    @router.callback_query(F.data == "add_template")
    async def add_template_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик добавления нового шаблона"""
        try:
            await state.set_state(TemplateStates.waiting_for_name)
            await safe_edit_text(
                callback.message,
                "<b>Создание нового шаблона</b>\n\n"
                "Введите название шаблона:",
                reply_markup=_cancel_keyboard(),
                parse_mode="HTML"
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в add_template_callback: {e}")
            await callback.answer(SOMETHING_WENT_WRONG)

    @router.callback_query(F.data == "create_template")
    async def create_template_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик создания шаблона из меню настроек"""
        try:
            await state.set_state(TemplateStates.waiting_for_name)
            await safe_edit_text(
                callback.message,
                "<b>Создание нового шаблона</b>\n\n"
                "Введите название шаблона:",
                reply_markup=_cancel_keyboard(),
                parse_mode="HTML"
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в create_template_callback: {e}")
            await callback.answer(SOMETHING_WENT_WRONG)

    @router.callback_query(F.data == "cancel_template_creation")
    async def cancel_template_creation_callback(callback: CallbackQuery, state: FSMContext):
        """Выход из любого шага создания шаблона."""
        try:
            await state.clear()
            await safe_edit_text(callback.message, "Создание шаблона отменено.")
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в cancel_template_creation_callback: {e}")
            await callback.answer(SOMETHING_WENT_WRONG)
    
    @router.message(TemplateStates.waiting_for_name)
    async def template_name_handler(message: Message, state: FSMContext):
        """Обработчик ввода названия шаблона"""
        try:
            name = message.text.strip()

            if _looks_like_command(name):
                # Неизвестная команда не должна стать названием шаблона.
                await state.clear()
                await safe_answer(message,
                    "Создание шаблона отменено. Отправьте команду ещё раз."
                )
                return

            if len(name) < 3:
                await message.answer("❌ Название должно содержать минимум 3 символа. Попробуйте еще раз:")
                return
            
            if len(name) > 100:
                await message.answer("❌ Название слишком длинное (максимум 100 символов). Попробуйте еще раз:")
                return
            
            await state.update_data(template_name=name)
            # Упрощенный сценарий: сразу переходим к содержимому шаблона
            await state.set_state(TemplateStates.waiting_for_content)

            await safe_answer(message,
                f"✅ Название сохранено: <b>{esc(name)}</b>\n\n"
                "Отправьте содержимое шаблона одним сообщением: Markdown-разметка "
                "и переменные в <code>{{ }}</code>.\n\n"
                "Основные переменные: <code>meeting_title</code>, <code>date</code>, "
                "<code>participants</code>, <code>decisions</code>, "
                "<code>action_items</code>, <code>risks_and_blockers</code>, "
                "<code>discussion</code>, <code>next_steps</code>.\n"
                "Оборачивайте секции в <code>{% if переменная %}</code> … "
                "<code>{% endif %}</code> — пустая секция не попадёт в протокол.\n\n"
                "Полная справка с примером: /templates → «Как устроены шаблоны».",
                reply_markup=_cancel_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в template_name_handler: {e}")
            await message.answer("❌ Произошла ошибка. Попробуйте еще раз.")
    
    # Шаг описания удалён в упрощённом сценарии
    
    @router.message(TemplateStates.waiting_for_content)
    async def template_content_handler(message: Message, state: FSMContext):
        """Обработчик ввода содержимого шаблона"""
        try:
            content = message.text.strip()

            if _looks_like_command(content):
                # Неизвестная команда не должна стать содержимым шаблона.
                await state.clear()
                await safe_answer(message,
                    "Создание шаблона отменено. Отправьте команду ещё раз."
                )
                return

            if len(content) < 10:
                await message.answer("❌ Содержимое шаблона слишком короткое (минимум 10 символов). Попробуйте еще раз:")
                return
            
            # Проверяем валидность шаблона
            try:
                template_service.validate_template_content(content)
            except TemplateValidationError as e:
                await message.answer(f"❌ {e.message}\n\nПопробуйте еще раз:")
                return
            
            await state.update_data(template_content=content)
            await state.set_state(TemplateStates.preview_template)
            
            # Показываем предварительный просмотр
            data = await state.get_data()
            await _show_template_preview(message, data, template_service)
            
        except Exception as e:
            logger.error(f"Ошибка в template_content_handler: {e}")
            await message.answer("❌ Произошла ошибка при обработке шаблона.")
    
    @router.callback_query(TemplateStates.preview_template, F.data == "save_template")
    async def save_template_callback(callback: CallbackQuery, state: FSMContext):
        """Сохранение шаблона"""
        try:
            data = await state.get_data()
            
            # Привязываем шаблон к внутреннему ID пользователя (а не Telegram ID)
            from src.services import UserService
            user_service = UserService()
            user = await user_service.get_or_create_user(
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name
            )

            template_create = TemplateCreate(
                name=data['template_name'],
                content=data['template_content'],
                description=data.get('template_description'),
                created_by=user.id
            )
            
            created_template = await template_service.create_template(template_create)
            
            await safe_edit_text(
                callback.message,
                f"✅ <b>Шаблон создан</b>\n\n"
                f"<b>Название:</b> {esc(created_template.name)}\n"
                f"<b>ID:</b> {esc(created_template.id)}\n\n"
                f"Теперь вы можете использовать этот шаблон при обработке файлов.",
                parse_mode="HTML"
            )
            
            logger.info(f"Пользователь {callback.from_user.id} создал шаблон '{created_template.name}'")
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении шаблона: {e}")
            await safe_edit_text(
                callback.message,
                "❌ Не удалось сохранить шаблон.\n"
                "Попробуйте ещё раз."
            )
        
        await state.clear()
        await callback.answer()
    
    @router.callback_query(TemplateStates.preview_template, F.data == "edit_template")
    async def edit_template_callback(callback: CallbackQuery, state: FSMContext):
        """Редактирование шаблона"""
        try:
            await state.set_state(TemplateStates.waiting_for_content)
            await safe_edit_text(
                callback.message,
                "<b>Редактирование шаблона</b>\n\n"
                "Введите новое содержимое шаблона:",
                parse_mode="HTML"
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в edit_template_callback: {e}")
            await callback.answer(SOMETHING_WENT_WRONG)
    
    @router.callback_query(TemplateStates.preview_template, F.data == "cancel_template")
    async def cancel_template_callback(callback: CallbackQuery, state: FSMContext):
        """Отмена создания шаблона"""
        try:
            await state.clear()
            await safe_edit_text(
                callback.message,
                "Создание шаблона отменено."
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в cancel_template_callback: {e}")
            await callback.answer(SOMETHING_WENT_WRONG)
    
    return router


async def _show_template_preview(message: Message, template_data: dict, template_service: TemplateService):
    """Показать предварительный просмотр шаблона"""
    try:
        # Создаем тестовые данные для предварительного просмотра
        test_variables = {
            "participants": "Иван Иванов, Петр Петров, Анна Сидорова",
            "date": "15.12.2024",
            "time": "14:00-15:30",
            "agenda": "1. Обсуждение планов на спринт\n2. Архитектурные решения\n3. Блокеры и риски",
            "discussion": "Обсуждались основные задачи предстоящего спринта...",
            "decisions": "1. Принято решение использовать новую архитектуру\n2. Выделены дополнительные ресурсы",
            "tasks": "1. Реализация API (Иван) - до 20.12\n2. Тестирование (Анна) - до 22.12",
            "next_steps": "1. Подготовка технических требований\n2. Создание тестовых сценариев",
            "key_points": "• Архитектура готова к внедрению\n• Команда готова к новому спринту",
            "action_items": "1. Настроить CI/CD\n2. Обновить документацию",
            "technical_issues": "Проблемы с производительностью базы данных",
            "architecture_decisions": "Переход на микросервисную архитектуру",
            "technical_tasks": "1. Оптимизация запросов\n2. Рефакторинг legacy кода",
            "risks_and_blockers": "• Нехватка времени на тестирование\n• Зависимость от внешнего API",
            "next_sprint_plans": "Фокус на backend разработке и тестировании"
        }
        
        # Рендерим шаблон с тестовыми данными
        rendered_template = template_service.render_template(
            template_data['template_content'], 
            test_variables
        )
        
        # Ограничиваем длину для предварительного просмотра
        preview_text = rendered_template[:2000] + "..." if len(rendered_template) > 2000 else rendered_template
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Сохранить", callback_data="save_template"),
                InlineKeyboardButton(text="Изменить", callback_data="edit_template")
            ],
            [
                InlineKeyboardButton(text="Отменить", callback_data="cancel_template")
            ]
        ])
        
        # Мягкое предупреждение: без {% if %} пустые поля оставят
        # заголовки над пустотой (принцип «ничего пустого» из PRODUCT.md).
        conditional_hint = ""
        if "{% if" not in template_data["template_content"]:
            conditional_hint = (
                "\n\n⚠️ В шаблоне нет условных секций <code>{% if переменная %}</code> … "
                "<code>{% endif %}</code> — если данных для поля не будет, его заголовок "
                "останется над пустым местом. Пример — в справке /templates."
            )

        # Опечатка в переменной иначе проявится только вечно пустой секцией.
        from src.services.template_variables import unknown_variables

        unknown_hint = ""
        unknown = unknown_variables(template_data["template_content"])
        if unknown:
            lines = []
            for var_name, suggestion in unknown.items():
                hint = f" (возможно, <code>{esc(suggestion)}</code>)" if suggestion else ""
                lines.append(f"• <code>{esc(var_name)}</code>{hint}")
            unknown_hint = (
                "\n\n⚠️ Переменные, которых нет в реестре полей — их секции "
                "останутся пустыми:\n" + "\n".join(lines)
            )

        description = template_data.get("template_description")
        description_html = esc(description) if description else "<i>Без описания</i>"

        preview_message = (
            f"<b>Предварительный просмотр шаблона</b>\n\n"
            f"<b>Название:</b> {esc(template_data['template_name'])}\n"
            f"<b>Описание:</b> {description_html}\n\n"
            f"<b>Результат с тестовыми данными:</b>\n\n"
            f"<pre>{esc(preview_text)}</pre>"
            f"{conditional_hint}"
            f"{unknown_hint}"
        )

        await safe_answer(message,
            preview_message,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при создании предварительного просмотра: {e}")
        await message.answer(
            "❌ Не удалось собрать предпросмотр шаблона.\n"
            "Проверьте разметку и переменные в шаблоне и пришлите его ещё раз."
        )
