"""Критика v10: один глиф — одно значение.

После канона v9 глифов стало 31 вместо 71, но два из них несли по семь ролей:
❌ значил и «ошибка», и «нет прав», и «пусто» (202 употребления, 19 файлов),
✅ — и «готово», и «нажми, чтобы сделать», и «это уже выбрано». Маркер с семью
значениями не маркирует ничего.

Словарь чата (протокол — отдельная поверхность, его секции не трогаем):
- ❌ — не получилось: сбой или отказ. Пустое состояние — не сбой, глифа нет.
- ✅ — сделано: терминальный успех. Кнопка-действие глиф не носит.
- ✓ — выбрано: маркер текущего значения в списках-переключателях.
"""

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"

# Поверхность чата. Протокол (protocol_briefs) и админские отчёты со своей
# легендой статусов здесь намеренно не участвуют.
_CHAT_MODULES = [
    "ux/message_builder.py",
    "ux/quick_actions.py",
    "ux/keyboards.py",
    "ux/speaker_mapping_ui.py",
    "handlers/callbacks/settings_callbacks.py",
    "handlers/callbacks/template_callbacks.py",
    "handlers/callbacks/template_mgmt_callbacks.py",
    "handlers/callbacks/processing_callbacks.py",
    "handlers/callbacks/protocol_actions_callbacks.py",
    "handlers/callbacks/protocol_header_callbacks.py",
    "handlers/command_handlers.py",
    "handlers/template_handlers.py",
    "handlers/participants_handlers.py",
]


def _strings(path: Path) -> list[str]:
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
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in logged and id(n) not in docstrings
    ]


def _button_labels(path: Path) -> list[str]:
    """Подписи кнопок: text= у InlineKeyboardButton / KeyboardButton."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    labels: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") not in {
            "InlineKeyboardButton", "KeyboardButton"
        }:
            continue
        for kw in node.keywords:
            if kw.arg == "text":
                for sub in ast.walk(kw.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        labels.append(sub.value)
    return labels


# ---------------------------------------------------------------------------
# ❌ — только сбой; пустое состояние глифа не носит
# ---------------------------------------------------------------------------


# Пустое состояние — это пустая коллекция, а не потерянное состояние обработки.
# «Файл не найден» остаётся сбоем: действие пользователя не удалось.
_EMPTY_STATE_PHRASES = ("шаблоны не найдены", "список участников пуст", "шаблонов пока нет")


def test_empty_states_do_not_wear_the_failure_glyph():
    """«Шаблоны не найдены» — не сбой, а пустое состояние."""
    offenders = []
    for module in _CHAT_MODULES:
        for text in _strings(_SRC / module):
            low = text.lower()
            if "❌" in text and any(phrase in low for phrase in _EMPTY_STATE_PHRASES):
                offenders.append(f"{module}: {text[:60]}")
    assert offenders == [], offenders


def test_lost_state_is_still_a_failure():
    """Обратная сторона правила: потеря файла — сбой, глиф остаётся."""
    strings = _strings(
        _SRC / "handlers" / "callbacks" / "processing_callbacks.py"
    )
    assert any("❌" in s and "Файл не найден" in s for s in strings)


# ---------------------------------------------------------------------------
# ✅ — только «сделано»; кнопка-действие глиф не носит
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", _CHAT_MODULES)
def test_action_buttons_do_not_wear_the_success_glyph(module):
    """«✅ Подтвердить» обещает «готово» до того, как что-то произошло."""
    offenders = [
        label for label in _button_labels(_SRC / module)
        if label.strip().startswith("✅")
    ]
    assert offenders == [], offenders


def test_selection_marker_is_the_same_glyph_everywhere():
    """Маркер «это выбрано» был ✅ на четырёх экранах и ✓ на пятом."""
    from src.ux.speaker_mapping_ui import SELECTED_MARK

    settings_src = (_SRC / "handlers" / "callbacks" / "settings_callbacks.py").read_text(
        encoding="utf-8"
    )
    # Настройки берут маркер из общего словаря, а не пишут свой глиф.
    assert "SELECTED_MARK" in settings_src
    assert '"✅ "' not in settings_src
    assert "'✅ '" not in settings_src
    assert SELECTED_MARK == "✓"


def test_selection_marker_is_not_the_success_glyph():
    from src.ux.speaker_mapping_ui import SELECTED_MARK

    assert SELECTED_MARK != "✅"


# ---------------------------------------------------------------------------
# Категории шаблонов не спорят с «Повесткой» и «Настройками»
# ---------------------------------------------------------------------------


def test_category_labels_carry_no_colliding_glyphs():
    from src.utils.template_sort import CATEGORY_LABELS

    for label in CATEGORY_LABELS.values():
        assert "📋" not in label, "📋 уже значит «Повестка дня» в протоколе"
        assert "⚙️" not in label, "⚙️ уже значит «Настройки»"


def test_category_labels_are_still_readable():
    from src.utils.template_sort import category_label

    assert category_label("general") == "Общие"
    assert category_label("technical") == "Технические"
    assert category_label("all") == "Все шаблоны"


# ---------------------------------------------------------------------------
# Меню команд Telegram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_menu_is_published_on_startup():
    """`set_my_commands` не вызывался нигде — меню «/» было пустым."""
    from unittest.mock import AsyncMock

    from src.ux.command_menu import publish_command_menu

    bot = AsyncMock()
    await publish_command_menu(bot)

    bot.set_my_commands.assert_awaited_once()
    commands = bot.set_my_commands.await_args.args[0]
    names = {c.command for c in commands}
    assert {"help", "templates", "settings"} <= names


@pytest.mark.asyncio
async def test_command_menu_failure_does_not_break_startup():
    from unittest.mock import AsyncMock

    from src.ux.command_menu import publish_command_menu

    bot = AsyncMock()
    bot.set_my_commands.side_effect = RuntimeError("telegram недоступен")
    await publish_command_menu(bot)  # не должно бросить
