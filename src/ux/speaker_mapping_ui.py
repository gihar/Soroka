"""
UI компоненты для подтверждения сопоставления спикеров с участниками
"""

from typing import Dict, List, Any, Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram import Bot
from loguru import logger

from src.utils.telegram_safe import safe_send_message
from src.utils.message_utils import escape_markdown_v2


def extract_speaker_quotes(
    diarization_data: Dict[str, Any],
    speaker_id: str,
    speakers_text: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """
    Извлечь первые 200 символов предобработанного текста спикера
    
    Args:
        diarization_data: Данные диаризации с сегментами (fallback если нет speakers_text)
        speaker_id: ID спикера (например, "SPEAKER_1")
        speakers_text: Словарь {speaker_id: полный_текст} с предобработанным текстом
        
    Returns:
        Строка с первыми 200 символами или None если текст не найден
    """
    # Приоритет: используем предобработанный текст если доступен
    if speakers_text and speaker_id in speakers_text:
        text = speakers_text[speaker_id].strip()
        if text:
            if len(text) > 200:
                return text[:200] + '...'
            return text
        return None
    
    # Fallback: собираем из сегментов если speakers_text недоступен
    segments = diarization_data.get('segments', [])
    speaker_segments = [s for s in segments if s.get('speaker') == speaker_id]
    
    if not speaker_segments:
        return None
    
    # Собираем текст последовательно из первых сегментов до 200 символов
    collected_text = []
    total_length = 0
    
    for seg in speaker_segments:
        text = seg.get('text', '').strip()
        if not text:
            continue
        
        text_length = len(text)
        if total_length + text_length <= 200:
            collected_text.append(text)
            total_length += text_length + 1  # +1 для пробела
        else:
            # Добавляем часть текста чтобы набрать 200 символов
            remaining = 200 - total_length
            if remaining > 0:
                collected_text.append(text[:remaining])
            break
    
    if not collected_text:
        return None
    
    result = ' '.join(collected_text)
    if len(result) > 200:
        return result[:200] + '...'
    
    return result


def format_mapping_message(
    speaker_mapping: Dict[str, str],
    diarization_data: Dict[str, Any],
    participants: List[Dict[str, str]],
    unmapped_speakers: Optional[List[str]] = None,
    speakers_text: Optional[Dict[str, str]] = None
) -> str:
    """
    Форматировать сообщение с информацией о сопоставлении спикеров
    
    Args:
        speaker_mapping: Словарь {speaker_id: participant_name}
        diarization_data: Данные диаризации
        participants: Список участников
        unmapped_speakers: Список несопоставленных спикеров
        speakers_text: Словарь {speaker_id: полный_текст} с предобработанным текстом
        
    Returns:
        Отформатированный текст сообщения в MarkdownV2
    """
    # Экранируем статический текст для MarkdownV2
    header_text = escape_markdown_v2("Проверьте сопоставление спикеров")
    lines = [f"🎭 *{header_text}*\n"]
    
    # Получаем всех спикеров из диаризации
    all_speakers = diarization_data.get('speakers', [])
    if not all_speakers:
        # Если speakers нет, извлекаем из segments
        segments = diarization_data.get('segments', [])
        all_speakers = sorted(set(s.get('speaker') for s in segments if s.get('speaker')))
    
    # Сортируем спикеров по порядку (SPEAKER_1, SPEAKER_2, ...)
    all_speakers.sort(key=lambda x: int(x.split('_')[-1]) if x.split('_')[-1].isdigit() else 999)
    
    # Отмечаем уже сопоставленных
    mapped_speakers = set(speaker_mapping.keys())
    if unmapped_speakers:
        unmapped_set = set(unmapped_speakers)
    else:
        unmapped_set = set(all_speakers) - mapped_speakers
    
    # Экранируем статический текст
    not_defined_text = escape_markdown_v2("Не определен")
    
    # Импортируем сервис для преобразования имен
    from src.services.participants_service import participants_service
    
    for speaker_id in all_speakers:
        participant_name = speaker_mapping.get(speaker_id)
        
        # Экранируем speaker_id для MarkdownV2
        escaped_speaker_id = escape_markdown_v2(speaker_id)
        
        if participant_name:
            # Сопоставлен - преобразуем в короткую форму и экранируем имя участника для MarkdownV2
            short_name = participants_service.convert_full_name_to_short(participant_name)
            escaped_participant_name = escape_markdown_v2(short_name)
            lines.append(f"*{escaped_speaker_id}* → {escaped_participant_name} ✓")
            
            # Извлекаем цитату (первые 200 символов)
            quote = extract_speaker_quotes(diarization_data, speaker_id, speakers_text=speakers_text)
            if quote:
                # Экранируем цитату для MarkdownV2
                escaped_quote = escape_markdown_v2(quote)
                # Экранируем кавычки для MarkdownV2 (кавычки - специальный символ)
                lines.append(f"  \\\"{escaped_quote}\\\"")
            lines.append("")
        else:
            # Не сопоставлен - экранируем текст
            lines.append(f"*{escaped_speaker_id}* → {not_defined_text} ❓")
            
            # Извлекаем цитату для несопоставленного
            quote = extract_speaker_quotes(diarization_data, speaker_id, speakers_text=speakers_text)
            if quote:
                # Экранируем цитату для MarkdownV2
                escaped_quote = escape_markdown_v2(quote)
                # Экранируем кавычки для MarkdownV2 (кавычки - специальный символ)
                lines.append(f"  \\\"{escaped_quote}\\\"")
            lines.append("")
    
    # Экранируем разделитель (дефисы нужно экранировать в MarkdownV2)
    separator = escape_markdown_v2("────────────────────────")
    lines.append(separator)
    
    return "\n".join(lines)


def _format_simple_mapping_message(
    speaker_mapping: Dict[str, str],
    diarization_data: Dict[str, Any],
    unmapped_speakers: Optional[List[str]] = None
) -> str:
    """
    Форматировать упрощенное сообщение без Markdown разметки (fallback)
    
    Args:
        speaker_mapping: Словарь {speaker_id: participant_name}
        diarization_data: Данные диаризации
        unmapped_speakers: Список несопоставленных спикеров
        
    Returns:
        Простой текст без Markdown разметки
    """
    lines = ["🎭 Проверьте сопоставление спикеров\n"]
    
    # Получаем всех спикеров из диаризации
    all_speakers = diarization_data.get('speakers', [])
    if not all_speakers:
        segments = diarization_data.get('segments', [])
        all_speakers = sorted(set(s.get('speaker') for s in segments if s.get('speaker')))
    
    # Сортируем спикеров по порядку
    all_speakers.sort(key=lambda x: int(x.split('_')[-1]) if x.split('_')[-1].isdigit() else 999)
    
    # Импортируем сервис для преобразования имен
    from src.services.participants_service import participants_service
    
    for speaker_id in all_speakers:
        participant_name = speaker_mapping.get(speaker_id)
        
        if participant_name:
            # Преобразуем в короткую форму перед отображением
            short_name = participants_service.convert_full_name_to_short(participant_name)
            lines.append(f"{speaker_id} → {short_name} ✓")
        else:
            lines.append(f"{speaker_id} → Не определен ❓")
    
    lines.append("\n────────────────────────")
    lines.append("\nИспользуйте кнопки ниже для подтверждения или изменения сопоставления.")
    
    return "\n".join(lines)


def create_mapping_keyboard(
    speaker_mapping: Dict[str, str],
    diarization_data: Dict[str, Any],
    participants: List[Dict[str, str]],
    user_id: int,
    current_editing_speaker: Optional[str] = None
) -> InlineKeyboardMarkup:
    """
    Создать inline-клавиатуру для подтверждения/изменения сопоставления
    
    Args:
        speaker_mapping: Текущее сопоставление
        diarization_data: Данные диаризации
        participants: Список участников
        user_id: ID пользователя
        current_editing_speaker: ID спикера, для которого показываем выбор участников
        
    Returns:
        InlineKeyboardMarkup с кнопками
    """
    keyboard_buttons = []
    
    # Если показываем выбор участников для конкретного спикера
    if current_editing_speaker:
        # Получаем всех спикеров
        all_speakers = diarization_data.get('speakers', [])
        if not all_speakers:
            segments = diarization_data.get('segments', [])
            all_speakers = sorted(set(s.get('speaker') for s in segments if s.get('speaker')))
        
        # Создаем кнопки для выбора участника
        used_participants = set(speaker_mapping.values())
        
        # Кнопка "Оставить без имени"
        keyboard_buttons.append([InlineKeyboardButton(
            text="❌ Оставить без имени",
            callback_data=f"sm_select:{current_editing_speaker}:none:{user_id}"
        )])
        
        # Кнопки с участниками
        for idx, participant in enumerate(participants):
            participant_name = participant.get('name', '')
            if not participant_name:
                continue
            
            # Используем короткое имя
            from src.services.participants_service import participants_service
            short_name = participants_service.convert_full_name_to_short(participant_name)
            
            # Проверяем, не используется ли уже этот участник
            is_used = participant_name in used_participants
            button_text = f"{'✓ ' if is_used else ''}{short_name}"
            
            keyboard_buttons.append([InlineKeyboardButton(
                text=button_text,
                callback_data=f"sm_select:{current_editing_speaker}:{idx}:{user_id}"
            )])
        
        # Кнопка "Назад"
        keyboard_buttons.append([InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"sm_cancel:{user_id}"
        )])
        
    else:
        # Основной вид: кнопки для изменения каждого спикера и действия
        all_speakers = diarization_data.get('speakers', [])
        if not all_speakers:
            segments = diarization_data.get('segments', [])
            all_speakers = sorted(set(s.get('speaker') for s in segments if s.get('speaker')))
        
        all_speakers.sort(key=lambda x: int(x.split('_')[-1]) if x.split('_')[-1].isdigit() else 999)
        
        # Каждая кнопка в отдельной строке (одна колонка)
        for speaker_id in all_speakers:
            participant_name = speaker_mapping.get(speaker_id)
            if participant_name:
                # Показываем короткое имя
                from src.services.participants_service import participants_service
                short_name = participants_service.convert_full_name_to_short(participant_name)
                button_text = f"✏️ {speaker_id}: {short_name}"
            else:
                button_text = f"➕ {speaker_id}"
            
            keyboard_buttons.append([InlineKeyboardButton(
                text=button_text,
                callback_data=f"sm_change:{speaker_id}:{user_id}"
            )])
        
        # Разделитель и основные действия
        keyboard_buttons.append([])  # Пустая строка для разделения
        
        keyboard_buttons.append([InlineKeyboardButton(
            text="✅ Подтвердить и продолжить",
            callback_data=f"sm_confirm:{user_id}"
        )])
        
        keyboard_buttons.append([InlineKeyboardButton(
            text="❌ Пропустить сопоставление",
            callback_data=f"sm_skip:{user_id}"
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)


async def show_mapping_confirmation(
    bot: Bot,
    chat_id: int,
    user_id: int,
    speaker_mapping: Dict[str, str],
    diarization_data: Dict[str, Any],
    participants: List[Dict[str, str]],
    unmapped_speakers: Optional[List[str]] = None,
    speakers_text: Optional[Dict[str, str]] = None
) -> Optional[Message]:
    """
    Показать UI для подтверждения сопоставления спикеров
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        user_id: ID пользователя
        speaker_mapping: Текущее сопоставление
        diarization_data: Данные диаризации
        participants: Список участников
        unmapped_speakers: Список несопоставленных спикеров
        speakers_text: Словарь {speaker_id: полный_текст} с предобработанным текстом
        
    Returns:
        Отправленное сообщение или None при ошибке
    """
    try:
        # Формируем текст сообщения
        message_text = format_mapping_message(
            speaker_mapping,
            diarization_data,
            participants,
            unmapped_speakers,
            speakers_text=speakers_text
        )
        
        # Создаем клавиатуру
        keyboard = create_mapping_keyboard(
            speaker_mapping,
            diarization_data,
            participants,
            user_id
        )
        
        # Отправляем сообщение с MarkdownV2
        message = await safe_send_message(
            bot=bot,
            chat_id=chat_id,
            text=message_text,
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )
        
        if message is None:
            # Если отправка с MarkdownV2 не удалась, пробуем без parse_mode
            logger.warning(f"Не удалось отправить UI с MarkdownV2 разметкой для пользователя {user_id}, пробую без разметки")
            
            # Создаем упрощенную версию без Markdown разметки
            simple_text = _format_simple_mapping_message(
                speaker_mapping,
                diarization_data,
                unmapped_speakers
            )
            
            try:
                message = await safe_send_message(
                    bot=bot,
                    chat_id=chat_id,
                    text=simple_text,
                    parse_mode=None,  # Без разметки
                    reply_markup=keyboard
                )
                
                if message:
                    logger.info(f"UI подтверждения сопоставления отправлен пользователю {user_id} без Markdown разметки")
                    return message
                else:
                    logger.error(f"Не удалось отправить упрощенную версию UI для пользователя {user_id}")
                    return None
                    
            except Exception as fallback_error:
                logger.error(f"Ошибка при отправке упрощенной версии UI: {fallback_error}", exc_info=True)
                return None
        else:
            logger.info(f"UI подтверждения сопоставления отправлен пользователю {user_id}")
            return message
        
    except Exception as e:
        logger.error(f"Ошибка при показе UI подтверждения сопоставления: {e}", exc_info=True)
        
        # Пробуем fallback без разметки
        try:
            simple_text = _format_simple_mapping_message(
                speaker_mapping,
                diarization_data,
                unmapped_speakers
            )
            
            keyboard = create_mapping_keyboard(
                speaker_mapping,
                diarization_data,
                participants,
                user_id
            )
            
            message = await safe_send_message(
                bot=bot,
                chat_id=chat_id,
                text=simple_text,
                parse_mode=None,
                reply_markup=keyboard
            )
            
            if message:
                logger.info(f"UI отправлен с fallback методом для пользователя {user_id}")
                return message
        except Exception as fallback_error:
            logger.error(f"Fallback также не удался: {fallback_error}", exc_info=True)
        
        return None


async def update_mapping_message(
    message: Message,
    speaker_mapping: Dict[str, str],
    diarization_data: Dict[str, Any],
    participants: List[Dict[str, str]],
    user_id: int,
    current_editing_speaker: Optional[str] = None,
    unmapped_speakers: Optional[List[str]] = None,
    speakers_text: Optional[Dict[str, str]] = None
) -> bool:
    """
    Обновить сообщение с сопоставлением
    
    Args:
        message: Сообщение для обновления
        speaker_mapping: Обновленное сопоставление
        diarization_data: Данные диаризации
        participants: Список участников
        user_id: ID пользователя
        current_editing_speaker: ID спикера, для которого показываем выбор
        unmapped_speakers: Список несопоставленных спикеров
        speakers_text: Словарь {speaker_id: полный_текст} с предобработанным текстом
        
    Returns:
        True если успешно, False при ошибке
    """
    try:
        from src.utils.telegram_safe import safe_edit_text
        
        message_text = format_mapping_message(
            speaker_mapping,
            diarization_data,
            participants,
            unmapped_speakers,
            speakers_text=speakers_text
        )
        
        keyboard = create_mapping_keyboard(
            speaker_mapping,
            diarization_data,
            participants,
            user_id,
            current_editing_speaker
        )
        
        await safe_edit_text(
            message,
            message_text,
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении сообщения сопоставления: {e}", exc_info=True)
        return False

