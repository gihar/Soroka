"""Tests for EnhancedLLMService — preset-based API."""
import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_generate_protocol_with_preset_delegates(monkeypatch):
    """The new entry point calls llm_manager.generate_protocol with the preset."""
    from src.services import enhanced_llm_service as ells_module

    # Mock the manager singleton inside the service
    fake_manager = MagicMock()
    fake_manager.generate_protocol = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(ells_module, "llm_manager", fake_manager)

    # Patch fallback_manager creator with a stub that just runs the primary handler
    class StubFallback:
        def __init__(self):
            self.primary = None
            self.last_execution = {"mode": "primary"}

        def set_primary(self, handler):
            self.primary = handler

        async def execute(self, *args, **kwargs):
            return await self.primary(*args, **kwargs)

        def get_stats(self):
            return {}

        def clear_cache(self):
            pass

    monkeypatch.setattr(ells_module, "create_llm_fallback_manager", lambda: StubFallback())

    svc = ells_module.EnhancedLLMService()
    preset = {"key": "k", "model": "gpt-4o-mini", "base_url": "u", "api_key": "a"}
    result = await svc.generate_protocol_with_preset(
        preset=preset,
        transcription="hello",
        template_variables={},
        diarization_data=None,
    )
    assert result == {"ok": True}
    fake_manager.generate_protocol.assert_called_once()
    _, kwargs = fake_manager.generate_protocol.call_args
    assert kwargs.get("preset") == preset
