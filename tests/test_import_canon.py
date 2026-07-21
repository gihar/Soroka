"""Страж импортного канона `src.` (ADR-0004).

Канон — единственный корень импорта: любой внутренний пакет из `src/` тянется
только по `src.`-пути. «Голый» импорт (`from reliability import …`,
`import services`) создаёт второй объект-модуль на другом корне sys.path и
тихо плодит дубли модульных синглтонов (баги #81 health_checker, #82
rate_limiter). Страж сканирует статически — не импортирует оба пути, потому что
sys.path в тестовом процессе загрязнён вставками других тест-файлов и
runtime-проверка тождества давала бы ложный результат.

Внутренние имена выводятся из самой файловой системы (дети `src/`), поэтому
новый пакет автоматически попадает под охрану. Относительные импорты (`.x`,
`..x`) легальны внутри пакета и канон не нарушают — страж их игнорирует.
"""
import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"


def _internal_names() -> set[str]:
    """Имена верхнего уровня под src/ — пакеты и модули (без дандеров)."""
    names: set[str] = set()
    for child in _SRC.iterdir():
        if child.name.startswith("__"):
            continue
        if child.is_dir():
            names.add(child.name)
        elif child.suffix == ".py":
            names.add(child.stem)
    return names


def _scanned_files() -> list[Path]:
    """Все .py под src/ плюс точка входа main.py."""
    return sorted(_SRC.rglob("*.py")) + [_ROOT / "main.py"]


def _bare_internal_imports(path: Path, internal: set[str]) -> list[str]:
    """Строки-нарушения канона в одном файле: (lineno, statement)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # level > 0 — относительный импорт, легален внутри пакета.
            if node.level != 0 or node.module is None:
                continue
            head = node.module.split(".", 1)[0]
            if head in internal:
                violations.append(f"L{node.lineno}: from {node.module} import …")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".", 1)[0]
                if head in internal:
                    violations.append(f"L{node.lineno}: import {alias.name}")
    return violations


def test_no_bare_internal_imports():
    """Ни один файл под src/ и main.py не импортирует внутренний пакет без src."""
    internal = _internal_names()
    offenders: dict[str, list[str]] = {}
    for path in _scanned_files():
        bare = _bare_internal_imports(path, internal)
        if bare:
            offenders[str(path.relative_to(_ROOT))] = bare

    assert not offenders, "Неканонические (голые) импорты внутренних пакетов:\n" + "\n".join(
        f"  {rel}\n    " + "\n    ".join(lines) for rel, lines in sorted(offenders.items())
    )


def test_main_has_no_src_syspath_insertion():
    """main.py не добавляет src/ вторым корнем в sys.path."""
    main_py = _ROOT / "main.py"
    tree = ast.parse(main_py.read_text(encoding="utf-8"), filename=str(main_py))

    def _is_syspath_mutation(call: ast.Call) -> bool:
        func = call.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"append", "insert"}:
            return False
        target = func.value  # ожидаем sys.path
        return (
            isinstance(target, ast.Attribute)
            and target.attr == "path"
            and isinstance(target.value, ast.Name)
            and target.value.id == "sys"
        )

    def _mentions_src(call: ast.Call) -> bool:
        return any(
            isinstance(sub, ast.Constant) and sub.value == "src"
            for sub in ast.walk(call)
        )

    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_syspath_mutation(node) and _mentions_src(node)
    ]
    assert not offenders, (
        f"main.py добавляет 'src' в sys.path (строки {offenders}) — это второй корень импорта"
    )
