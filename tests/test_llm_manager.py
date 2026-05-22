"""Tests for LLMManager (single-provider, preset-based)."""
import importlib.util
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

_manager_path = os.path.join(os.path.dirname(__file__), "..", "src", "llm", "manager.py")

# Pre-register a fake openai_provider so manager.py import does not need real OpenAI deps
fake = type(sys)("fake")
fake.OpenAIProvider = MagicMock
sys.modules.setdefault("src.llm.providers.openai_provider", fake)

_spec = importlib.util.spec_from_file_location("llm_manager", _manager_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
LLMManager = _mod.LLMManager


@pytest.mark.asyncio
async def test_manager_passes_preset_to_provider():
    manager = LLMManager.__new__(LLMManager)
    mock_provider = MagicMock()
    mock_provider.is_available.return_value = True
    mock_provider.generate_protocol = AsyncMock(return_value={"summary": "test"})
    manager.providers = {"openai": mock_provider}

    preset = {"key": "k1", "model": "gpt-4o-mini", "base_url": "u", "api_key": "a"}
    result = await manager.generate_protocol(
        preset=preset,
        transcription="text",
        template_variables={"summary": "S"},
    )
    assert result == {"summary": "test"}
    _, kwargs = mock_provider.generate_protocol.call_args
    assert kwargs.get("preset") == preset


@pytest.mark.asyncio
async def test_manager_raises_when_openai_unavailable():
    manager = LLMManager.__new__(LLMManager)
    mock_provider = MagicMock()
    mock_provider.is_available.return_value = False
    manager.providers = {"openai": mock_provider}

    with pytest.raises(ValueError):
        await manager.generate_protocol(
            preset={"key": "k", "model": "m"},
            transcription="",
            template_variables={},
        )
