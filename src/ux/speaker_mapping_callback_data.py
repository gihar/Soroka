"""Типизированные фабрики callback-данных Карточки сопоставления (sm_*).

Родные ``CallbackData`` aiogram вместо ручной сборки/разбора f-строк. Wire-формат
неизменен: префиксы и порядок полей ровно как в старых кнопках, разделитель — ``:``
по умолчанию, — чтобы кнопки уже отправленных карточек продолжили работать после
деплоя. Проверяется тестом контракта ``tests/test_speaker_mapping_callback_data.py``.
"""

from aiogram.filters.callback_data import CallbackData


class SmChange(CallbackData, prefix="sm_change"):
    """Начать смену сопоставления спикера: ``sm_change:{speaker_id}:{user_id}``."""

    speaker_id: str
    user_id: int


class SmSelect(CallbackData, prefix="sm_select"):
    """Выбор участника для спикера: ``sm_select:{speaker_id}:{participant_idx}:{user_id}``.

    ``participant_idx`` — строка: несёт индекс участника ("0", "1", …) либо литерал
    "none" (кнопка «Оставить без имени»). Строка, а не ``Optional[int]``, потому что
    aiogram сериализует ``None`` в пустую строку и сломал бы wire-формат ("none").
    """

    speaker_id: str
    participant_idx: str
    user_id: int


class SmCancel(CallbackData, prefix="sm_cancel"):
    """Возврат к основному виду карточки: ``sm_cancel:{user_id}``."""

    user_id: int


class SmConfirm(CallbackData, prefix="sm_confirm"):
    """Подтверждение сопоставления: ``sm_confirm:{user_id}``."""

    user_id: int


class SmSkip(CallbackData, prefix="sm_skip"):
    """Пропуск сопоставления: ``sm_skip:{user_id}``."""

    user_id: int


class SmSkipConfirm(CallbackData, prefix="sm_skipok"):
    """Подтверждённый пустой пропуск: ``sm_skipok:{user_id}``.

    Кнопка «Да, продолжить» из под-вида подтверждения пропуска. Отдельный
    префикс, а не ``sm_skip``: у ``sm_skip`` теперь роль развилки (показать
    подтверждение либо продолжить), а финальное продолжение без имён — это
    ``sm_skipok`` с атомарным изъятием сессии.
    """

    user_id: int
