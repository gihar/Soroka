"""Повестка и проекты встречи из одного сообщения пользователя.

Ввод — одно сообщение: всё до строки «Проекты: …» — повестка, сама строка и всё
после неё — список проектов. Отдельного шага под проекты нет: настройка обработки
и так длинная, а проекты нужны редко.
"""

import re
from typing import Optional, Tuple

# «Проекты:», «проекты —», «Проекты - …» в начале строки.
_PROJECTS_LINE = re.compile(r"^\s*проекты\s*[:\-—–]\s*(.*)$", re.IGNORECASE)


def _or_none(text: str) -> Optional[str]:
    text = text.strip()
    return text or None


def split_agenda_and_projects(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Разделить сообщение на (повестка, проекты); пустая часть — None."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _PROJECTS_LINE.match(line)
        if match:
            agenda = "\n".join(lines[:index])
            projects = "\n".join([match.group(1), *lines[index + 1:]])
            return _or_none(agenda), _or_none(projects)
    return _or_none(text), None
