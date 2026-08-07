"""Типизированные фабрики callback-данных обкатки модели (proto_model*).

Ключ пресета — строка произвольной формы («qwen-token-plan»), поэтому ручная
сборка f-строк и разбор ``rsplit("_")``, как у остальных кнопок под протоколом,
здесь разошлись бы на первом же ключе с подчёркиванием. Родные ``CallbackData``
aiogram разбирают по ``:`` и знают типы полей.

Префиксы намеренно не начинаются с ``proto_regen_``: там уже висит общий
``startswith``-обработчик выбора шаблона, и любое пересечение сделало бы порядок
регистрации несущей конструкцией.
"""

from aiogram.filters.callback_data import CallbackData


class ProtoModels(CallbackData, prefix="proto_models"):
    """Открыть экран выбора модели: ``proto_models:{history_id}``."""

    history_id: int


class ProtoModelGo(CallbackData, prefix="proto_model_go"):
    """Перегенерация записи выбранным пресетом: ``proto_model_go:{history_id}:{preset_key}``."""

    history_id: int
    preset_key: str
