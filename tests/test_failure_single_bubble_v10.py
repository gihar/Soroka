"""Критика v10: сбой присылает один пузырь, а не два — и без литеральных звёздочек.

На каждый упавший прогон уходило ДВА сообщения: трекер показывал выверенный
голос ошибки из ``error_presentation`` («что + шаг», ветка по причине сбоя), а
следом воркер слал `_get_error_recommendation` **без parse_mode**. Пользователь
видел литеральное `⚠️ **Сервис временно недоступен**` со звёздочками, местами
противоречащее первому сообщению («максимум 20MB» против «МБ»).

Это было единственное место, где канон разметки ломался: все остальные 63
литерала с HTML-тегами уходят с parse_mode="HTML".

Требование «не протекать сырым payload провайдера» никуда не делось — оно
просто переехало на живой путь (``error_presentation``), а не на мёртвый
форматтер, чей текст уходил только в лог.
"""

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from src.services import error_presentation

RAW_402 = (
    "Error code: 402 - {'error': {'message': 'This request requires more credits, "
    "or fewer max_tokens. You requested up to 16384 tokens, but can only afford "
    "6109.', 'code': 402}, 'user_id': 'user_2lpA5W2gt60hAGWIkHfhzCdz90y'}"
)

_SRC = Path(__file__).resolve().parent.parent / "src"


def _user_facing_strings(path: Path) -> list[str]:
    """Строковые литералы модуля вне logger-вызовов."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    logged: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            target = getattr(func, "value", None)
            name = getattr(target, "id", "")
            if name in {"logger", "logging"}:
                for arg in ast.walk(node):
                    logged.add(id(arg))
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in logged
    ]


# ---------------------------------------------------------------------------
# Второй пузырь удалён вместе с источником звёздочек
# ---------------------------------------------------------------------------


def test_recommendation_builder_is_gone():
    from src.services.task_queue_manager import TaskQueueManager

    assert not hasattr(TaskQueueManager, "_get_error_recommendation")


def test_worker_failure_path_sends_nothing_beyond_the_tracker():
    """В обработчике исключения воркера не должно остаться send_message."""
    from src.services.task_queue_manager import TaskQueueManager

    source = inspect.getsource(TaskQueueManager._process_task)
    tree = ast.parse(textwrap.dedent(source))

    # Нужен внешний try/except/finally воркера, а не вложенные try внутри него.
    outer = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Try) and node.finalbody and node.handlers
    )
    sent_to_task_chat = [
        node for handler in outer.handlers for node in ast.walk(handler)
        if isinstance(node, ast.Attribute) and node.attr == "chat_id"
        and getattr(node.value, "id", "") == "task"
    ]
    # Алерт админам остаётся — он адресован не пользователю задачи.
    assert sent_to_task_chat == [], "воркер снова шлёт пользователю второй пузырь"


def test_no_markdown_bold_survives_in_queue_manager():
    """Литеральные `**` — класс багов, а не стиль: канон разметки HTML."""
    strings = _user_facing_strings(_SRC / "services" / "task_queue_manager.py")
    offenders = [s for s in strings if "**" in s]
    assert offenders == []


def test_dead_queue_error_screen_is_gone():
    """`show_error` не вызывался ниоткуда и путал следующую критику."""
    from src.ux.queue_tracker import QueuePositionTracker

    assert not hasattr(QueuePositionTracker, "show_error")


# ---------------------------------------------------------------------------
# Живой путь: голос ошибки без утечки payload
# ---------------------------------------------------------------------------


def test_credits_failure_does_not_leak_provider_payload():
    text = error_presentation.processing_failure_message("Анализ", RAW_402)
    low = text.lower()
    assert "user_id" not in low
    assert "max_tokens" not in low
    assert "402" not in text


def test_credits_failure_says_it_is_our_side():
    """Совет «пришлите файл поменьше» на нехватку кредитов замыкал круг."""
    text = error_presentation.processing_failure_message("Анализ", RAW_402)
    assert "другой файл" not in text.lower()


def test_failure_message_always_offers_a_next_step():
    for raw in (RAW_402, "Файл слишком большой", "timeout", "неведомая ошибка"):
        text = error_presentation.processing_failure_message("Анализ", raw)
        assert len(text.splitlines()) >= 2, f"нет следующего шага для «{raw}»"


@pytest.mark.parametrize("raw", [RAW_402, "MemoryError", "timeout"])
def test_failure_message_carries_no_markdown_asterisks(raw):
    assert "**" not in error_presentation.processing_failure_message("Анализ", raw)
