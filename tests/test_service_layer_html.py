"""Сервисный слой говорит валидной разметкой.

Канонический формат текстов — Markdown; транспортная граница (rate limiter)
рендерит его в Telegram HTML. Прямые вызовы aiogram мимо safe-обёрток
запрещены для parse_mode="Markdown" — они уходят в чат с битым жирным.
"""

import ast
from pathlib import Path

import pytest

from src.reliability.telegram_rate_limiter import telegram_rate_limiter

SAFE_WRAPPERS = {
    "safe_answer",
    "safe_edit_text",
    "safe_send_message",
    "safe_bot_edit_message",
    "safe_send_document",
    "safe_send_with_retry",
    "try_send_or_log",
}


# ---------------------------------------------------------------------------
# Граница: канонический Markdown -> Telegram HTML
# ---------------------------------------------------------------------------

async def _capture_send(captured):
    async def fake_send(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    return fake_send


@pytest.mark.asyncio
async def test_positional_text_rendered_to_html():
    captured = {}
    sent = await telegram_rate_limiter.safe_send_with_retry(
        await _capture_send(captured),
        "**Готово** и <5 минут",
        chat_id=1,
        parse_mode="Markdown",
    )
    assert sent is not None
    assert captured["kwargs"]["parse_mode"] == "HTML"
    assert captured["args"][0] == "<b>Готово</b> и &lt;5 минут"


@pytest.mark.asyncio
async def test_keyword_text_rendered_to_html():
    captured = {}
    await telegram_rate_limiter.safe_send_with_retry(
        await _capture_send(captured),
        chat_id=1,
        text="## Заголовок\n- пункт",
        parse_mode="Markdown",
    )
    assert captured["kwargs"]["parse_mode"] == "HTML"
    assert captured["kwargs"]["text"] == "<b>Заголовок</b>\n• пункт"


@pytest.mark.asyncio
async def test_caption_rendered_to_html():
    captured = {}
    await telegram_rate_limiter.safe_send_with_retry(
        await _capture_send(captured),
        chat_id=1,
        caption="**Файл** готов",
        parse_mode="Markdown",
    )
    assert captured["kwargs"]["parse_mode"] == "HTML"
    assert captured["kwargs"]["caption"] == "<b>Файл</b> готов"


@pytest.mark.asyncio
async def test_html_sends_pass_through_unchanged():
    captured = {}
    await telegram_rate_limiter.safe_send_with_retry(
        await _capture_send(captured),
        "<b>уже HTML</b>",
        chat_id=1,
        parse_mode="HTML",
    )
    assert captured["args"][0] == "<b>уже HTML</b>"
    assert captured["kwargs"]["parse_mode"] == "HTML"


# ---------------------------------------------------------------------------
# Заслон: legacy parse_mode="Markdown" только внутри safe-обёрток
# ---------------------------------------------------------------------------

def _markdown_call_sites():
    violations = []
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            has_legacy = any(
                kw.arg == "parse_mode"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "Markdown"
                for kw in node.keywords
            )
            if not has_legacy:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "?")
            if name not in SAFE_WRAPPERS:
                violations.append(f"{path}:{node.lineno} {name}")
    return violations


def test_no_legacy_markdown_outside_safe_wrappers():
    violations = _markdown_call_sites()
    assert not violations, "\n".join(violations)
