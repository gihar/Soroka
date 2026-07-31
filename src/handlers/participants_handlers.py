"""
Обработчики для работы со списком участников встречи
"""

from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from src.handlers.participants_states import ParticipantsInput
from src.services.participants_service import participants_service
from src.services.user_service import UserService
from src.utils.date_format import format_russian_date
from src.utils.telegram_safe import safe_answer
from src.ux.html_text import esc

# Формулировки, нужные нескольким хендлерам этого модуля: одна на всех, иначе
# правка голоса поправит одну копию из трёх (критика v10).
_FORM_OPEN_FAILED = (
    "❌ Не удалось открыть форму.\n"
    "Попробуйте ещё раз."
)
_CONTINUE_FAILED = (
    "❌ Не удалось продолжить.\n"
    "Отправьте запись заново."
)


async def dismiss_participants_menu(bot, state: Optional[FSMContext]) -> None:
    """Погасить кнопки меню участников после ухода потока вперёд.

    Меню оставалось в чате нажимаемым: тап через минуту после старта обработки
    уводил в ввод участников, выбор шаблона и заканчивался «Запись потерялась»
    — четыре шага в никуда (критика v11). Best-effort: сообщение могли удалить,
    и падать из-за этого поток не имеет права.
    """
    if state is None:
        return
    try:
        menu = (await state.get_data()).get("participants_menu")
    except Exception:
        return
    if not menu:
        return

    await state.update_data(participants_menu=None)
    try:
        await bot.edit_message_reply_markup(
            chat_id=menu["chat_id"], message_id=menu["message_id"],
            reply_markup=None,
        )
    except Exception as e:
        logger.debug(f"Меню участников уже не погасить: {e}")


async def show_participants_menu(
    message: Message,
    user_service: UserService,
    user_id: Optional[int] = None,
    state: Optional[FSMContext] = None,
):
    """Показать экран «Участники встречи» — он же шаг ввода.

    Экран обещает ввод текстом, поэтому сам его и открывает: до критики v11
    FSM-состояние здесь не выставлялось, и выполнивший инструкцию дословно
    получал в ответ «отправьте файл или ссылку». Отдельная кнопка «Добавить
    участников» после этого не нужна — приглашение осталось только как экран
    «⬅️ Назад» с подтверждения разбора.

    Кнопка сохранённого списка строится по владельцу диалога. При вызове из
    колбэка message принадлежит боту, поэтому реальный ID пользователя нужно
    передать явно через user_id (ср. real_user_id в _show_template_selection_step2).
    """
    try:
        # Проверяем, есть ли сохраненный список у владельца диалога
        owner_id = user_id if user_id is not None else message.from_user.id
        user = await user_service.get_user_by_telegram_id(owner_id)

        keyboard_buttons = []

        # Saved participants — show first if available
        if user and user.saved_participants:
            try:
                saved = participants_service.participants_from_json(user.saved_participants)
                if saved:
                    keyboard_buttons.append([InlineKeyboardButton(
                        text=f"Использовать сохраненный ({len(saved)} чел.)",
                        callback_data="use_saved_participants"
                    )])
            except Exception:
                pass

        # Skip
        keyboard_buttons.append([InlineKeyboardButton(
            text="⏭ Без участников",
            callback_data="skip_participants"
        )])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        # Дата встречи — единственный реквизит, которого нет в аудио: без неё в
        # шапку уходит день обработки. Приглашение целиком отдаёт её вместе с
        # темой и участниками, поэтому стоит первым.
        message_text = (
            "<b>Участники встречи</b>\n\n"
            "Пришлите приглашение или письмо целиком — возьму оттуда "
            "участников, дату и тему.\n\n"
            "Или просто список, по одному на строку:\n"
            "• <code>Иван Петров, руководитель</code>\n"
            "• <code>Мария Иванова - разработчик</code>\n\n"
            "Без даты в шапку протокола попадёт день обработки — "
            "поправить можно и после готового протокола."
        )

        if state is not None:
            await state.set_state(ParticipantsInput.waiting_for_participants)

        sent = await safe_answer(message,
            message_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        # Запоминаем меню, чтобы погасить его кнопки, когда поток уйдёт вперёд.
        if state is not None and sent is not None:
            await state.update_data(participants_menu={
                "chat_id": sent.chat.id, "message_id": sent.message_id,
            })

    except Exception as e:
        logger.error(f"Ошибка при показе меню участников: {e}")
        await message.answer(
            "❌ Не удалось открыть меню участников.\n"
            "Отправьте запись заново."
        )


def setup_participants_handlers() -> Router:
    """Настройка обработчиков для работы с участниками"""
    router = Router()
    user_service = UserService()
    
    @router.callback_query(F.data == "input_new_participants")
    async def prompt_participants_input(callback: CallbackQuery, state: FSMContext):
        """Запрос ввода нового списка участников"""
        try:
            await callback.answer()
            await state.set_state(ParticipantsInput.waiting_for_participants)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")]
            ])

            # Дата встречи — единственный реквизит, которого нет в аудио: без
            # неё в шапку уходит день обработки. Приглашение отдаёт её вместе с
            # темой и участниками, поэтому подсказка про него стоит первой —
            # раньше эта возможность работала, но нигде не была описана.
            await safe_answer(callback.message,
                "<b>Кто был на встрече и когда она была?</b>\n\n"
                "Пришлите приглашение или письмо целиком — возьму оттуда "
                "участников, дату и тему.\n\n"
                "Или просто список участников, по одному на строку:\n"
                "• <code>Иван Петров, руководитель</code>\n"
                "• <code>Мария Иванова - разработчик</code>\n"
                "• <code>Ольга Сидорова</code>\n\n"
                "Без даты в шапку протокола попадёт день обработки — "
                "поправить можно и после готового протокола.\n\n"
                "Или отправьте /cancel для отмены.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Ошибка при запросе ввода участников: {e}")
            await callback.message.answer(
                _FORM_OPEN_FAILED
            )
    
    @router.callback_query(F.data == "use_saved_participants")
    async def use_saved_participants(callback: CallbackQuery, state: FSMContext):
        """Использование сохраненного списка участников"""
        try:
            await callback.answer()
            
            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            
            if not user or not user.saved_participants:
                await callback.message.answer(
                    "❌ У вас нет сохраненного списка участников."
                )
                return
            
            # Загружаем сохраненный список
            participants = participants_service.participants_from_json(user.saved_participants)
            
            if not participants:
                await callback.message.answer(
                    "❌ Не удалось загрузить сохраненный список."
                )
                return
            
            # Сохраняем в состояние
            await state.update_data(participants_list=participants)
            
            # Показываем подтверждение
            display_text = participants_service.format_participants_for_display(participants)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Использовать", callback_data="confirm_participants")]
            ])
            
            await safe_answer(callback.message,
                f"{display_text}\n\n<b>Использовать этот список?</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке сохраненного списка: {e}")
            await callback.message.answer(
                "❌ Не удалось загрузить сохранённый список.\n"
                "Введите участников заново или пропустите шаг."
            )
    
    @router.callback_query(F.data == "skip_participants")
    async def skip_participants(callback: CallbackQuery, state: FSMContext):
        """Пропуск добавления участников"""
        try:
            await callback.answer("Участники не будут добавлены")
            
            # Очищаем участников из состояния
            await state.update_data(participants_list=None)
            
            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state, real_user_id=callback.from_user.id)
            
        except Exception as e:
            logger.error(f"Ошибка при пропуске участников: {e}")
            await callback.message.answer(
                _CONTINUE_FAILED
            )
    
    @router.message(ParticipantsInput.waiting_for_participants, F.content_type == "text")
    async def handle_participants_text(message: Message, state: FSMContext):
        """Обработка текстового ввода списка участников"""
        try:
            text = message.text.strip()

            # Гибридный подход: пробуем автоизвлечение, затем обычный парсинг
            meeting_info = participants_service.extract_from_meeting_text(text)
            
            # Всегда парсим весь текст как обычный список участников
            text_participants = participants_service.parse_participants_text(text)
            
            # Объединяем участников из обоих источников
            all_participants = []
            participants_dict = {}  # Для избежания дубликатов по имени
            
            # Добавляем участников из meeting_info (если есть)
            if meeting_info and meeting_info.participants:
                for participant in meeting_info.participants:
                    key = participant.name.lower().strip()
                    if key not in participants_dict:
                        participants_dict[key] = {
                            "name": participant.name,
                            "role": participant.role or ""
                        }
                        all_participants.append(participants_dict[key])
            
            # Добавляем участников из обычного парсинга
            for participant in text_participants:
                key = participant["name"].lower().strip()
                if key not in participants_dict:
                    participants_dict[key] = participant
                    all_participants.append(participant)

            # Проверяем, есть ли участники
            if not all_participants:
                await safe_answer(message,
                    "❌ Не удалось найти участников в этом тексте.\n"
                    "Пришлите список участников или отправьте /cancel.",
                    parse_mode="HTML"
                )
                return

            # Валидируем объединенный список
            is_valid, error_message = participants_service.validate_participants(all_participants)
            if not is_valid:
                await safe_answer(message,
                    f"❌ {esc(error_message)}\n"
                    "Поправьте список и отправьте ещё раз или /cancel.",
                    parse_mode="HTML"
                )
                return

            # Если есть информация о встрече (тема/дата), используем её
            if meeting_info and (meeting_info.topic or meeting_info.start_time):
                # Сохраняем информацию о встрече в состояние
                await state.update_data(meeting_info=meeting_info.model_dump())
                await state.update_data(participants_list=all_participants)

                # Сохраняем тему и дату для использования в промптах
                if meeting_info.topic:
                    await state.update_data(meeting_topic=meeting_info.topic)
                if meeting_info.start_time:
                    # Русский формат: дата встаёт в шапку рядом с датой обработки
                    # («30 июля 2026»), и «27.07.2026» читался бы разнобоем.
                    await state.update_data(meeting_date=format_russian_date(
                        meeting_info.start_time
                    ))
                    await state.update_data(meeting_time=meeting_info.start_time.strftime("%H:%M"))

                await state.set_state(ParticipantsInput.confirm_meeting_info)

                # Показываем извлеченную информацию
                display_text = participants_service.format_meeting_info_for_display(meeting_info)
                
                # Добавляем предупреждение если есть
                warning_text = ""
                if meeting_info.topic == "Не указана":
                    warning_text = "\n\n⚠️ Тема встречи не указана, будет использовано значение по умолчанию"

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Использовать", callback_data="confirm_meeting_info"),
                        InlineKeyboardButton(text="Сохранить и использовать", callback_data="save_meeting_info")
                    ],
                    [
                        InlineKeyboardButton(text="⬅️ Назад", callback_data="input_new_participants"),
                        InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")
                    ]
                ])

                await safe_answer(message,
                    f"<b>Автоматически извлечена информация о встрече:</b>\n\n"
                    f"{display_text}{warning_text}\n\n<b>Использовать эту информацию?</b>",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

            else:
                # Обычный список участников без информации о встрече
                await state.update_data(participants_list=all_participants)
                await state.set_state(ParticipantsInput.confirm_participants)

                # Показываем для подтверждения
                display_text = participants_service.format_participants_for_display(all_participants)

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Подтвердить", callback_data="confirm_participants"),
                        InlineKeyboardButton(text="Сохранить и использовать", callback_data="save_and_confirm_participants")
                    ],
                    [
                        InlineKeyboardButton(text="⬅️ Назад", callback_data="input_new_participants"),
                        InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_participants")
                    ]
                ])

                await safe_answer(message,
                    f"{display_text}\n\n<b>Все верно?</b>",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

        except Exception as e:
            logger.error(f"Ошибка при обработке текста участников: {e}")
            await message.answer(
                "❌ Не удалось разобрать список участников.\n"
                "Проверьте формат и отправьте ещё раз."
            )
    
    @router.callback_query(F.data == "confirm_meeting_info")
    async def confirm_meeting_info(callback: CallbackQuery, state: FSMContext):
        """Подтверждение автоматически извлеченной информации о встрече"""
        try:
            # Получаем количество участников для сообщения
            data = await state.get_data()
            participants = data.get('participants_list', [])
            participants_count = len(participants)

            await callback.answer("✅ Информация о встрече подтверждена")

            # Детальное логирование для отладки ID пользователей
            logger.info(f"[DEBUG] Callback - from_user.id={callback.from_user.id}, message.from_user.id={callback.message.from_user.id}")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            template_service = TemplateService()
            # Передаем real_user_id из callback для правильного определения пользователя
            await _show_template_selection_step2(callback.message, template_service, state, participants_count, real_user_id=callback.from_user.id)

        except Exception as e:
            logger.error(f"Ошибка при подтверждении информации о встрече: {e}")
            await callback.message.answer(
                _CONTINUE_FAILED
            )

    @router.callback_query(F.data == "save_meeting_info")
    async def save_meeting_info(callback: CallbackQuery, state: FSMContext):
        """Сохранение и подтверждение автоматически извлеченной информации"""
        try:
            data = await state.get_data()
            meeting_info_data = data.get('meeting_info', {})

            if not meeting_info_data:
                await callback.answer("❌ Информация о встрече не найдена", show_alert=True)
                return

            # Сохраняем список участников для пользователя
            participants = data.get('participants_list', [])
            participants_count = len(participants)
            
            if participants:
                participants_json = participants_service.participants_to_json([
                    {"name": p["name"], "role": p.get("role", "")}
                    for p in participants
                ])

                # Обновляем пользователя в БД
                from src.database import user_repo
                await user_repo.update_saved_participants(callback.from_user.id, participants_json)

            await callback.answer("✅ Информация сохранена и будет использована")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state, participants_count, real_user_id=callback.from_user.id)

        except Exception as e:
            logger.error(f"Ошибка при сохранении информации о встрече: {e}")
            await callback.message.answer(
                "❌ Не удалось сохранить информацию.\n"
                "Попробуйте ещё раз."
            )

    @router.callback_query(F.data == "confirm_participants")
    async def confirm_participants(callback: CallbackQuery, state: FSMContext):
        """Подтверждение списка участников"""
        try:
            # Получаем количество участников для сообщения
            data = await state.get_data()
            participants = data.get('participants_list', [])
            participants_count = len(participants)

            await callback.answer("✅ Список участников подтвержден")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state, participants_count, real_user_id=callback.from_user.id)

        except Exception as e:
            logger.error(f"Ошибка при подтверждении участников: {e}")
            await callback.message.answer(
                _CONTINUE_FAILED
            )
    
    @router.callback_query(F.data == "save_and_confirm_participants")
    async def save_and_confirm_participants(callback: CallbackQuery, state: FSMContext):
        """Сохранение и подтверждение списка участников"""
        try:
            data = await state.get_data()
            participants = data.get('participants_list', [])
            participants_count = len(participants)

            if not participants:
                await callback.answer("Список участников пуст", show_alert=True)
                return

            # Сохраняем список для пользователя
            participants_json = participants_service.participants_to_json(participants)

            # Обновляем пользователя в БД
            from src.database import user_repo
            await user_repo.update_saved_participants(callback.from_user.id, participants_json)

            await callback.answer("✅ Список сохранен и будет использован")

            # Переходим к выбору шаблона (шаг 2)
            from src.handlers.message_handlers import _show_template_selection_step2
            from src.services.template_service import TemplateService

            template_service = TemplateService()
            await _show_template_selection_step2(callback.message, template_service, state, participants_count, real_user_id=callback.from_user.id)

        except Exception as e:
            logger.error(f"Ошибка при сохранении участников: {e}")
            await callback.message.answer(
                "❌ Не удалось сохранить список.\n"
                "Попробуйте ещё раз."
            )
    
    @router.callback_query(F.data == "cancel_participants")
    async def cancel_participants(callback: CallbackQuery, state: FSMContext):
        """Отмена ввода участников"""
        try:
            await callback.answer("Ввод отменен")
            await state.clear()
            await callback.message.answer("Ввод участников отменен.")
            
        except Exception as e:
            logger.error(f"Ошибка при отмене: {e}")

    # Обработчики для дополнительной информации о протоколе
    return router
