"""Tests for LLM manager fallback logic."""
import importlib.util
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

# Import manager module directly to avoid triggering heavy provider imports.
# We mock providers anyway, so we just need the LLMManager class.
_manager_path = os.path.join(os.path.dirname(__file__), "..", "src", "llm", "manager.py")

# Pre-register fake modules so manager.py's imports don't fail
for mod_name in [
    "src.llm.providers.openai_provider",
    "src.llm.providers.anthropic_provider",
    "src.llm.providers.yandex_provider",
]:
    if mod_name not in sys.modules:
        fake = type(sys)("fake")
        fake.OpenAIProvider = MagicMock
        fake.AnthropicProvider = MagicMock
        fake.YandexGPTProvider = MagicMock
        sys.modules[mod_name] = fake

_spec = importlib.util.spec_from_file_location("llm_manager", _manager_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
LLMManager = _mod.LLMManager


@pytest.mark.asyncio
async def test_manager_uses_requested_provider():
    """Manager should use the requested provider when available."""
    manager = LLMManager.__new__(LLMManager)

    mock_provider = MagicMock()
    mock_provider.is_available.return_value = True
    mock_provider.generate_protocol = AsyncMock(
        return_value={"summary": "test"}
    )
    manager.providers = {"test_provider": mock_provider}

    result = await manager.generate_protocol(
        provider_name="test_provider",
        transcription="test text",
        template_variables={"summary": "Summary"},
    )
    assert result == {"summary": "test"}
    mock_provider.generate_protocol.assert_called_once()


@pytest.mark.asyncio
async def test_manager_raises_for_unknown_provider():
    """Manager should raise for unknown provider name."""
    manager = LLMManager.__new__(LLMManager)
    manager.providers = {}

    with pytest.raises(ValueError, match="Неизвестный провайдер"):
        await manager.generate_protocol(
            provider_name="nonexistent",
            transcription="test",
            template_variables={},
        )


@pytest.mark.asyncio
async def test_manager_raises_for_unavailable_provider():
    """Manager should raise for unavailable provider."""
    manager = LLMManager.__new__(LLMManager)

    mock_provider = MagicMock()
    mock_provider.is_available.return_value = False
    manager.providers = {"test": mock_provider}

    with pytest.raises(ValueError, match="недоступен"):
        await manager.generate_protocol(
            provider_name="test",
            transcription="test",
            template_variables={},
        )


@pytest.mark.asyncio
async def test_manager_fallback_on_failure():
    """Manager should fall back to next provider on failure."""
    manager = LLMManager.__new__(LLMManager)

    failing_provider = MagicMock()
    failing_provider.is_available.return_value = True
    failing_provider.generate_protocol = AsyncMock(side_effect=Exception("API down"))

    working_provider = MagicMock()
    working_provider.is_available.return_value = True
    working_provider.generate_protocol = AsyncMock(
        return_value={"summary": "fallback"}
    )

    manager.providers = {"openai": failing_provider, "anthropic": working_provider}

    result = await manager.generate_protocol_with_fallback(
        preferred_provider="openai",
        transcription="test text",
        template_variables={"summary": "Summary"},
    )
    assert result == {"summary": "fallback"}
    failing_provider.generate_protocol.assert_awaited_once()
    working_provider.generate_protocol.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_fallback_all_fail():
    """Manager should raise when all providers fail."""
    manager = LLMManager.__new__(LLMManager)

    failing1 = MagicMock()
    failing1.is_available.return_value = True
    failing1.generate_protocol = AsyncMock(side_effect=Exception("fail1"))

    failing2 = MagicMock()
    failing2.is_available.return_value = True
    failing2.generate_protocol = AsyncMock(side_effect=Exception("fail2"))

    manager.providers = {"openai": failing1, "yandex": failing2}

    with pytest.raises(ValueError, match="Все доступные провайдеры"):
        await manager.generate_protocol_with_fallback(
            preferred_provider="openai",
            transcription="test",
            template_variables={},
        )


@pytest.mark.asyncio
async def test_manager_get_available_providers():
    """get_available_providers returns only providers that are available."""
    manager = LLMManager.__new__(LLMManager)

    available = MagicMock()
    available.is_available.return_value = True

    unavailable = MagicMock()
    unavailable.is_available.return_value = False

    manager.providers = {"openai": available, "yandex": unavailable}

    result = manager.get_available_providers()
    assert "openai" in result
    assert "yandex" not in result
