"""
FSM состояния для работы со списком участников
"""

from aiogram.fsm.state import State, StatesGroup


class ParticipantsInput(StatesGroup):
    """Состояния для ввода списка участников"""
    waiting_for_participants = State()  # Ожидание ввода списка (текст или файл)
    confirm_participants = State()  # Подтверждение распарсенного списка
    confirm_meeting_info = State()  # Подтверждение автоматически извлеченной информации


class SpeakerMappingEdit(StatesGroup):
    """Состояния для редактирования сопоставления спикеров"""
    selecting_speaker = State()  # Выбор спикера для изменения
    selecting_participant = State()  # Выбор участника для спикера
    confirm_changes = State()  # Подтверждение изменений


class SpeakerMappingStates(StatesGroup):
    """Состояния для подтверждения сопоставления спикеров"""
    waiting_confirmation = State()  # Ожидание подтверждения сопоставления


