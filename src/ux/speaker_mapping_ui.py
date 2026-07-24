"""
UI компоненты для подтверждения сопоставления спикеров с участниками
"""

from typing import Dict, List, Optional, Set

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from loguru import logger

from src.models.diarization import Diarization
from src.ux.card_content import MappingCard, PlainCard, SpeakerRow
from src.ux.card_sender import edit_card, send_card
from src.ux.speaker_mapping_callback_data import (
    SmCancel,
    SmChange,
    SmConfirm,
    SmSelect,
    SmSkip,
    SmSkipConfirm,
)

# Подсказка-следствие внизу карточки: показывается, только когда в карточке есть
# несопоставленные спикеры. Одна строка, без назидательности — читателю видно,
# во что превратятся неназванные спикеры в готовом протоколе.
_UNMAPPED_HINT = "Неназванные спикеры попадут в протокол как «Участник N»"


def _speaker_order(diarization: Optional[Diarization]) -> List[str]:
    """Спикеры в порядке их появления в сегментах (единый источник для карточки)."""
    return list(diarization.speakers) if diarization else []


def extract_speaker_quotes(
    diarization: Optional[Diarization],
    speaker_id: str,
    speakers_text: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """
    Извлечь первые 200 символов предобработанного текста спикера

    Args:
        diarization: Диаризация с сегментами (fallback если нет speakers_text)
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
    segments = diarization.segments if diarization else []
    speaker_segments = [s for s in segments if s.speaker == speaker_id]

    if not speaker_segments:
        return None

    # Собираем текст последовательно из первых сегментов до 200 символов
    collected_text = []
    total_length = 0

    for seg in speaker_segments:
        text = seg.text.strip()
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


def _card_header(
    participants: List[Dict[str, str]],
    current_editing_speaker: Optional[str],
) -> str:
    """Заголовок карточки под текущий вид.

    Под-вид спикера (``current_editing_speaker`` задан) называет редактируемого
    спикера и приглашает печатать (ADR-0006): без списка участников — только
    «отправьте сообщением», со списком — «…или выберите ниже». Главный вид —
    «проверьте сопоставление» при наличии списка, «назовите спикеров (по
    желанию)» без него (ADR-0002).
    """
    if current_editing_speaker:
        if participants:
            return (
                f"✏️ Имя для {current_editing_speaker} — "
                "отправьте сообщением или выберите ниже"
            )
        return f"✏️ Имя для {current_editing_speaker} — отправьте сообщением"

    return (
        "Проверьте сопоставление спикеров"
        if participants
        else "Назовите спикеров (по желанию)"
    )


def build_mapping_card(
    speaker_mapping: Dict[str, str],
    diarization: Optional[Diarization],
    participants: List[Dict[str, str]],
    unmapped_speakers: Optional[List[str]] = None,
    speakers_text: Optional[Dict[str, str]] = None,
    speakers_with_audio: Optional[Set[str]] = None,
    current_editing_speaker: Optional[str] = None,
) -> MappingCard:
    """
    Собрать семантическое содержимое Карточки сопоставления (ADR-0005).

    Возвращает MappingCard — заголовок и строки спикеров с цитатами; разметку
    (Telegram HTML) и plain-страховку добавляет отправитель карточек. Экранированием
    и параллельными копиями текста эта функция больше не занимается.

    Args:
        speaker_mapping: Словарь {speaker_id: participant_name}
        diarization: Диаризация
        participants: Список участников
        unmapped_speakers: Список несопоставленных спикеров (не влияет на состав строк)
        speakers_text: Словарь {speaker_id: полный_текст} с предобработанным текстом
        speakers_with_audio: Спикеры с доставленным фрагментом записи — их цитата
            уже в подписи фрагмента, в карточке не дублируется
        current_editing_speaker: спикер открытого под-вида — заголовок называет
            его и приглашает отправить имя (None — главный вид)

    Returns:
        MappingCard с заголовком и строками спикеров в порядке их появления
    """
    # Импортируем сервис для преобразования имен
    from src.services.participants_service import participants_service

    header = _card_header(participants, current_editing_speaker)

    rows: List[SpeakerRow] = []
    # Спикеры — в порядке их появления в диаризации
    for speaker_id in _speaker_order(diarization):
        participant_name = speaker_mapping.get(speaker_id)
        display_name = (
            participants_service.convert_full_name_to_short(participant_name)
            if participant_name
            else None
        )

        # Цитата спикера показывается один раз: если фрагмент записи доставлен,
        # она уже в его подписи — в карточке не дублируем.
        quote = None
        if not (speakers_with_audio and speaker_id in speakers_with_audio):
            quote = extract_speaker_quotes(
                diarization, speaker_id, speakers_text=speakers_text
            )

        rows.append(
            SpeakerRow(speaker_id=speaker_id, display_name=display_name, quote=quote)
        )

    # Есть хоть один несопоставленный спикер → подсказываем следствие (nudge).
    hint = _UNMAPPED_HINT if any(r.display_name is None for r in rows) else None

    return MappingCard(header=header, rows=tuple(rows), hint=hint)


def create_mapping_keyboard(
    speaker_mapping: Dict[str, str],
    diarization: Optional[Diarization],
    participants: List[Dict[str, str]],
    user_id: int,
    current_editing_speaker: Optional[str] = None
) -> InlineKeyboardMarkup:
    """
    Создать inline-клавиатуру для подтверждения/изменения сопоставления

    Args:
        speaker_mapping: Текущее сопоставление
        diarization: Диаризация
        participants: Список участников
        user_id: ID пользователя
        current_editing_speaker: ID спикера, для которого показываем выбор участников

    Returns:
        InlineKeyboardMarkup с кнопками
    """
    keyboard_buttons = []

    # Если показываем выбор участников для конкретного спикера
    if current_editing_speaker:
        # Создаем кнопки для выбора участника
        used_participants = set(speaker_mapping.values())
        
        # Кнопка "Оставить без имени". Имя человека, которого нет в списке,
        # вводится прямо сообщением — под-вид уже ждёт текст (ADR-0006),
        # промежуточной кнопки «Ввести имя вручную» больше нет.
        keyboard_buttons.append([InlineKeyboardButton(
            text="❌ Оставить без имени",
            callback_data=SmSelect(
                speaker_id=current_editing_speaker,
                participant_idx="none",
                user_id=user_id,
            ).pack()
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
                callback_data=SmSelect(
                    speaker_id=current_editing_speaker,
                    participant_idx=str(idx),
                    user_id=user_id,
                ).pack()
            )])

        # Кнопка "Назад"
        keyboard_buttons.append([InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=SmCancel(user_id=user_id).pack()
        )])
        
    else:
        # Основной вид: кнопки для изменения каждого спикера и действия
        all_speakers = _speaker_order(diarization)

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
                callback_data=SmChange(
                    speaker_id=speaker_id, user_id=user_id
                ).pack()
            )])

        # Разделитель и основные действия
        keyboard_buttons.append([])  # Пустая строка для разделения

        keyboard_buttons.append([InlineKeyboardButton(
            text="✅ Подтвердить и продолжить",
            callback_data=SmConfirm(user_id=user_id).pack()
        )])

        keyboard_buttons.append([InlineKeyboardButton(
            text="❌ Пропустить сопоставление",
            callback_data=SmSkip(user_id=user_id).pack()
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)


def format_skip_confirm_message() -> PlainCard:
    """Содержимое под-вида подтверждения пустого пропуска (ADR-0005): простой экран.

    Называет цену одной строкой и переспрашивает — без назидательности. Тот же
    отправитель карточек доставит его как обычный текст.
    """
    return PlainCard(
        text="⚠️ Спикеры останутся метками «Участник N». Продолжить?"
    )


def create_skip_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура под-вида подтверждения пропуска: две кнопки.

    «Да, продолжить» (``sm_skipok``) — финальное продолжение без имён; «Назвать
    спикеров» возвращает к основному виду карточки тем же ``sm_cancel``, что и
    прочие возвраты (оттуда доступен ручной ввод имени).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Да, продолжить",
            callback_data=SmSkipConfirm(user_id=user_id).pack(),
        )],
        [InlineKeyboardButton(
            text="✏️ Назвать спикеров",
            callback_data=SmCancel(user_id=user_id).pack(),
        )],
    ])


async def show_mapping_confirmation(
    bot: Bot,
    chat_id: int,
    user_id: int,
    speaker_mapping: Dict[str, str],
    diarization: Optional[Diarization],
    participants: List[Dict[str, str]],
    unmapped_speakers: Optional[List[str]] = None,
    speakers_text: Optional[Dict[str, str]] = None,
    speakers_with_audio: Optional[Set[str]] = None
) -> Optional[Message]:
    """Показать Карточку сопоставления новым сообщением (ADR-0005).

    Адаптер над отправителем карточек: собирает семантическое содержимое и
    клавиатуру, доставку (HTML → при неудаче plain-страховка) выполняет
    ``send_card``.

    Returns:
        Отправленное сообщение или None при ошибке
    """
    content = build_mapping_card(
        speaker_mapping,
        diarization,
        participants,
        unmapped_speakers,
        speakers_text=speakers_text,
        speakers_with_audio=speakers_with_audio,
    )
    keyboard = create_mapping_keyboard(
        speaker_mapping, diarization, participants, user_id
    )

    message = await send_card(bot, chat_id, content, keyboard)
    if message is None:
        logger.error(f"Не удалось показать карточку сопоставления пользователю {user_id}")
    else:
        logger.info(f"Карточка сопоставления показана пользователю {user_id}")
    return message


async def update_mapping_message(
    message: Message,
    speaker_mapping: Dict[str, str],
    diarization: Optional[Diarization],
    participants: List[Dict[str, str]],
    user_id: int,
    current_editing_speaker: Optional[str] = None,
    unmapped_speakers: Optional[List[str]] = None,
    speakers_text: Optional[Dict[str, str]] = None,
    speakers_with_audio: Optional[Set[str]] = None
) -> bool:
    """Перерисовать Карточку сопоставления на месте (ADR-0005).

    Адаптер над отправителем карточек: тот же единый контракт доставки, что и при
    первичном показе (HTML → при неудаче plain-страховка).

    Returns:
        True если сообщение обновлено, False при ошибке
    """
    content = build_mapping_card(
        speaker_mapping,
        diarization,
        participants,
        unmapped_speakers,
        speakers_text=speakers_text,
        speakers_with_audio=speakers_with_audio,
        current_editing_speaker=current_editing_speaker,
    )
    keyboard = create_mapping_keyboard(
        speaker_mapping,
        diarization,
        participants,
        user_id,
        current_editing_speaker,
    )

    edited = await edit_card(message, content, keyboard)
    if edited is None:
        logger.error(f"Не удалось перерисовать карточку сопоставления для пользователя {user_id}")
    return edited is not None

