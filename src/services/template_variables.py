"""Реестр переменных протокола и проверка кастомных шаблонов.

Контракт извлечения полей держится на именах переменных: опечатка
({{ decisons }}) иначе проявляется только вечно пустой секцией без сигнала.
Реестр = поля с правилами в промптах + переменные системных шаблонов.
"""

import difflib
from functools import lru_cache
from typing import Dict, Optional

from jinja2 import Environment, meta

from src.prompts.prompts import FIELD_SPECIFIC_RULES


@lru_cache(maxsize=1)
def known_variables() -> frozenset:
    from src.services.template_library import TemplateLibrary

    names = set(FIELD_SPECIFIC_RULES)
    env = Environment()
    for template in TemplateLibrary().get_all_templates():
        names |= meta.find_undeclared_variables(env.parse(template["content"]))
    return frozenset(names)


def unknown_variables(content: str) -> Dict[str, Optional[str]]:
    """Переменные шаблона вне реестра: имя -> близкое известное имя или None."""
    env = Environment()
    try:
        used = meta.find_undeclared_variables(env.parse(content))
    except Exception:
        # Синтаксис проверяется отдельной валидацией; здесь не дублируем ошибку.
        return {}

    known = known_variables()
    result: Dict[str, Optional[str]] = {}
    for name in sorted(used - known):
        match = difflib.get_close_matches(name, known, n=1, cutoff=0.75)
        result[name] = match[0] if match else None
    return result
