"""Сопоставление спикеров ходит через protocol_generator.structured_call (#38)."""
from unittest.mock import AsyncMock

import pytest

from src.config import settings


async def test_mapping_call_uses_structured_call(monkeypatch):
    import src.services.speaker_mapping_service as sms

    fake_result = {
        "speaker_mappings": {"SPEAKER_0": "Анна"},
        "unmapped_speakers": [],
        "confidence_scores": {"SPEAKER_0": 0.9},
    }
    fake_call = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(sms.protocol_generator, "structured_call", fake_call)

    service = sms.SpeakerMappingService()
    result = await service._call_llm_for_mapping("промпт с диалогом", "openai")

    assert result == fake_result
    kwargs = fake_call.call_args.kwargs
    assert kwargs["user_prompt"] == "промпт с диалогом"
    assert kwargs["model"] == settings.speaker_mapping_model
    assert kwargs["schema"] is sms.SPEAKER_MAPPING_SCHEMA


async def test_mapping_for_unknown_provider_returns_empty(monkeypatch):
    import src.services.speaker_mapping_service as sms

    fake_call = AsyncMock()
    monkeypatch.setattr(sms.protocol_generator, "structured_call", fake_call)

    service = sms.SpeakerMappingService()
    result = await service._call_llm_for_mapping("промпт", "yandex")

    assert result == {}
    fake_call.assert_not_awaited()


async def test_mapping_llm_error_is_typed(monkeypatch):
    import src.services.speaker_mapping_service as sms
    from src.services.speaker_mapping_service import SpeakerMappingLLMError

    fake_call = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(sms.protocol_generator, "structured_call", fake_call)

    service = sms.SpeakerMappingService()
    with pytest.raises(SpeakerMappingLLMError):
        await service._call_llm_for_mapping("промпт", "openai")
