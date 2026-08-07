"""Команда /check_model — тонкая обёртка над зондом строгих схем (issue #116).

Проверяется ровно то, что принадлежит команде: кому она отвечает, чей вердикт
показывает и как отличает недоступность провайдера от вердикта о схеме. Сам
вердикт считает зонд (`tests/test_protocol_generator.py`), команда его не
пересчитывает.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.llm.protocol_generator import SchemaProbeVerdict

QWEN_PRESET = {
    "key": "qwen_plus",
    "name": "Qwen: plus",
    "model": "qwen3.7-plus",
    "base_url": "https://token-plan.example/compatible-mode/v1",
    "is_enabled": True,
}


def _check_model_handler():
    """Хендлер /check_model из собранного роутера команд управления пресетами."""
    import src.handlers.admin_model_handlers as ah

    router = ah.setup_admin_model_handlers()
    handler = next(
        h.callback for h in router.message.handlers
        if h.callback.__name__ == "check_model_handler"
    )
    return ah, handler


def _message(text: str = "/check_model qwen_plus", user_id: int = 1):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


@pytest.fixture
def probe(monkeypatch):
    """Зонд как единственный источник вердикта — подменяем его целиком."""
    from src.llm import protocol_generator

    probe_mock = AsyncMock()
    monkeypatch.setattr(protocol_generator, "probe_schema_support", probe_mock)
    return probe_mock


@pytest.fixture
def preset_lookup(monkeypatch):
    import src.database as db_module

    monkeypatch.setattr(
        db_module.model_preset_repo, "get_by_key",
        AsyncMock(return_value=QWEN_PRESET),
    )


@pytest.fixture
def shown(monkeypatch):
    """Текст, который увидел администратор вместо строки ожидания."""
    import src.handlers.admin_model_handlers as ah

    captured = {}

    async def fake_edit(_message, text, **kwargs):
        captured["text"] = text

    monkeypatch.setattr(ah, "safe_edit_text", fake_edit)
    return captured


async def test_check_model_refuses_a_non_admin(monkeypatch, probe):
    """Зонд тратит квоту провайдера — команда только для администратора."""
    ah, handler = _check_model_handler()
    monkeypatch.setattr(ah, "is_admin", lambda _uid: False)

    message = _message()
    await handler(message)

    probe.assert_not_awaited()
    message.answer.assert_awaited_once_with(ah.ACCESS_DENIED)


async def test_check_model_shows_the_verdict_of_the_probe(monkeypatch, probe, preset_lookup, shown):
    """Команда показывает вердикт зонда, называя проверенные модель и адрес."""
    ah, handler = _check_model_handler()
    monkeypatch.setattr(ah, "is_admin", lambda _uid: True)
    probe.return_value = SchemaProbeVerdict(
        schema_honored=False,
        model="qwen3.6-flash",
        base_url="https://token-plan.example/compatible-mode/v1",
        requested_keys=("zqx_marker", "unlikely_count"),
        returned_keys=("answer", "confidence"),
    )

    await handler(_message())

    assert probe.await_args.kwargs["preset"] == QWEN_PRESET
    text = shown["text"]
    assert "принята и выброшена" in text
    assert "qwen3.6-flash" in text
    assert "https://token-plan.example/compatible-mode/v1" in text


async def test_check_model_tells_a_refused_key_apart_from_a_verdict(
    monkeypatch, probe, preset_lookup, shown
):
    """Провайдер не пустил — это не вердикт о схеме, и команда так и говорит."""
    ah, handler = _check_model_handler()
    monkeypatch.setattr(ah, "is_admin", lambda _uid: True)
    probe.side_effect = Exception("Error code: 401 - Invalid API key provided")

    await handler(_message())

    text = shown["text"]
    assert "Вердикта о схеме нет" in text
    assert "Ключ не принят" in text
    assert "применяется" not in text and "выброшена" not in text
