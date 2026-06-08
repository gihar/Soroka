"""The speaker-mapping LLM call must fail LOUDLY, not silently.

A hard LLM/API error (e.g. HTTP 400 invalid schema) must be distinguishable from
a genuinely-empty mapping. The service raises SpeakerMappingLLMError internally and
map_speakers_to_participants logs a greppable marker, then degrades to ({}, "general")
so the protocol still generates.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_mapping_llm_failure_is_loud_and_degrades(monkeypatch):
    from loguru import logger

    from src.services.speaker_mapping_service import (
        SpeakerMappingLLMError,
        SpeakerMappingService,
    )

    service = SpeakerMappingService()

    # Force a non-empty speakers_info so we reach the LLM call, and a trivial prompt.
    monkeypatch.setattr(
        service,
        "_extract_speakers_info",
        lambda *a, **k: [{"speaker": "SPEAKER_1", "samples": ["привет"]}],
    )
    monkeypatch.setattr(service, "_build_mapping_prompt", lambda *a, **k: "prompt")

    async def _raise(*a, **k):
        raise SpeakerMappingLLMError("HTTP 400 invalid schema")

    monkeypatch.setattr(service, "_call_llm_for_mapping", _raise)

    # Capture loguru ERROR output.
    records = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        mapping, meeting_type = await service.map_speakers_to_participants(
            diarization_data={"speakers": ["SPEAKER_1"], "segments": []},
            participants=[{"name": "Иван Петров", "role": "PM"}],
            transcription_text="...",
            llm_provider="openai",
        )
    finally:
        logger.remove(sink_id)

    assert mapping == {}
    assert meeting_type == "general"
    assert any("SPEAKER_MAPPING_LLM_FAILED" in str(r) for r in records), (
        "hard LLM failure must be logged with the SPEAKER_MAPPING_LLM_FAILED marker"
    )


@pytest.mark.asyncio
async def test_empty_mapping_is_not_treated_as_failure(monkeypatch):
    """A successful call returning no confident matches is NOT a failure: no marker."""
    from loguru import logger

    from src.services.speaker_mapping_service import SpeakerMappingService

    service = SpeakerMappingService()
    monkeypatch.setattr(
        service,
        "_extract_speakers_info",
        lambda *a, **k: [{"speaker": "SPEAKER_1", "samples": ["привет"]}],
    )
    monkeypatch.setattr(service, "_build_mapping_prompt", lambda *a, **k: "prompt")

    async def _empty(*a, **k):
        return {"meeting_type": "business", "speaker_mappings": {}}

    monkeypatch.setattr(service, "_call_llm_for_mapping", _empty)

    records = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        mapping, meeting_type = await service.map_speakers_to_participants(
            diarization_data={"speakers": ["SPEAKER_1"], "segments": []},
            participants=[{"name": "Иван Петров", "role": "PM"}],
            transcription_text="...",
            llm_provider="openai",
        )
    finally:
        logger.remove(sink_id)

    assert mapping == {}
    assert meeting_type == "business"
    assert not any("SPEAKER_MAPPING_LLM_FAILED" in str(r) for r in records)
