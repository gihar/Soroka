"""Отображаемая подпись анонимного спикера (доменный словарь: «Спикер»).

Диаризация выдаёт технические метки «SPEAKER_N». Пользователю их показывают
как «Спикер N» — по словарю CONTEXT.md «Спикер» — анонимный голос из
диаризации. Меняется только отображение: сам ``speaker_id`` (ключ сопоставления
и callback_data) остаётся «SPEAKER_N».
"""

import re

_SPEAKER_LABEL_RE = re.compile(r"^SPEAKER_?(\d+)$", re.IGNORECASE)


def humanize_speaker_label(speaker_id: str) -> str:
    """«SPEAKER_1» → «Спикер 1» для показа пользователю.

    Метка не по шаблону возвращается как есть — страховка на случай нестандартных
    идентификаторов бэкенда транскрипции.
    """
    match = _SPEAKER_LABEL_RE.match(speaker_id.strip())
    if not match:
        return speaker_id
    return f"Спикер {int(match.group(1))}"
