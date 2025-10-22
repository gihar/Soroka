"""
FSM состояния для работы со списком участников
"""

from aiogram.fsm.state import State, StatesGroup


class ParticipantsInput(StatesGroup):
    """Состояния для ввода списка участников"""
    waiting_for_participants = State()  # Ожидание ввода списка (текст или файл)
    confirm_participants = State()  # Подтверждение распарсенного списка
    confirm_meeting_info = State()  # Подтверждение автоматически извлеченной информации


