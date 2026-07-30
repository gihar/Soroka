"""Критика v10: одна формулировка — одно место в коде.

31 точный дубль строк длиннее 30 символов, и расходящиеся пары на один и тот же
случай: «Проверьте формат и отправьте ещё раз» против «…и пришлите ещё раз».
Пока текст живёт в четырнадцати местах, следующая правка голоса неизбежно
поправит тринадцать из них.
"""

import ast
from collections import Counter
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"


# Поверхности, которые говорят с пользователем. src/utils сюда не входит:
# там живёт и внутренняя телеметрия (token_cache_logger), чьи «notes» — не текст
# для чата.
_SPEAKING_DIRS = ("ux", "handlers", "services")


def _all_user_strings() -> Counter:
    counter: Counter = Counter()
    paths = [p for d in _SPEAKING_DIRS for p in (_SRC / d).rglob("*.py")]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        logged: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                owner = getattr(getattr(node.func, "value", None), "id", "")
                if owner in {"logger", "logging"}:
                    for arg in ast.walk(node):
                        logged.add(id(arg))
        docstrings = {
            id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) > 30
                and id(node) not in logged
                and id(node) not in docstrings
                # Только русский текст: отсекает SQL и англоязычные фрагменты логов.
                and any("а" <= ch.lower() <= "я" for ch in node.value)
            ):
                counter[node.value] += 1
    return counter


def test_no_user_string_is_written_more_than_twice():
    """Порог мягкий: две копии — терпимо, четырнадцать — источник расхождений."""
    repeated = {text: n for text, n in _all_user_strings().items() if n > 2}
    assert repeated == {}, repeated


def test_permission_refusal_lives_in_one_place():
    from src.ux.admin_views import ACCESS_DENIED

    assert "прав" in ACCESS_DENIED.lower()


def test_templates_load_failure_lives_in_one_place():
    from src.ux.message_builder import TEMPLATES_LOAD_FAILED

    assert "шаблон" in TEMPLATES_LOAD_FAILED.lower()
    # Голос «что + шаг»: у ошибки обязан быть следующий шаг.
    assert "\n" in TEMPLATES_LOAD_FAILED


def test_missing_protocol_lives_in_one_place():
    from src.ux.message_builder import PROTOCOL_GONE

    assert "истори" in PROTOCOL_GONE.lower()


def test_retry_verb_is_consistent():
    """«отправьте ещё раз» и «пришлите ещё раз» на один случай — разнобой."""
    counter = _all_user_strings()
    said = " ".join(counter)
    assert "пришлите ещё раз" not in said, "глагол повтора приведён к «отправьте»"
