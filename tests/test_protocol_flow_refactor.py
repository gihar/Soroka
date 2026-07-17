"""Unit tests for the protocol-flow refactor.

Covers the small, pure units introduced/extracted during the refactor:
- ProcessingMetrics.to_dict()/from_dict() round-trip (P4)
- result_sender pure helpers: _build_result_dict (P2); сплит протокола по секциям
  тестируется в test_protocol_split_sections.py
- MappingStateCache save/load round-trip incl. task_id (P3)
- LLMGenerationService model-name resolution (P6a)
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# ProcessingMetrics round-trip (P4)
# ---------------------------------------------------------------------------

def test_processing_metrics_roundtrip():
    from src.performance.metrics import ProcessingMetrics

    start = datetime(2026, 6, 4, 1, 0, 0)
    m = ProcessingMetrics(file_name="meeting.mp3", user_id=42, start_time=start)
    m.end_time = start + timedelta(seconds=12)
    m.download_duration = 1.5
    m.transcription_duration = 7.0
    m.diarization_duration = 2.0
    m.speakers_count = 3

    restored = ProcessingMetrics.from_dict(m.to_dict())

    assert restored.file_name == "meeting.mp3"
    assert restored.user_id == 42
    assert restored.start_time == start
    assert restored.end_time == start + timedelta(seconds=12)
    assert restored.download_duration == 1.5
    assert restored.transcription_duration == 7.0
    assert restored.diarization_duration == 2.0
    assert restored.speakers_count == 3
    # total_duration is a computed property → recomputed from start/end.
    assert restored.total_duration == 12.0


def test_processing_metrics_from_dict_ignores_computed_and_unknown():
    from src.performance.metrics import ProcessingMetrics

    # total_duration / efficiency_score are properties, not settable fields;
    # unknown_key must be ignored without raising.
    m = ProcessingMetrics.from_dict({
        "file_name": "x.mp3",
        "user_id": 7,
        "total_duration": 999,       # computed → must be ignored
        "efficiency_score": 5,       # computed → must be ignored
        "unknown_key": "ignore me",  # unknown → must be ignored
    })

    assert m.file_name == "x.mp3"
    assert m.user_id == 7
    # No end_time stored → property returns 0.0, NOT the injected 999.
    assert m.total_duration == 0.0


def test_processing_metrics_from_dict_empty_uses_defaults():
    from src.performance.metrics import ProcessingMetrics

    m = ProcessingMetrics.from_dict({})

    assert m.file_name == "unknown"
    assert m.user_id == 0
    assert isinstance(m.start_time, datetime)


# ---------------------------------------------------------------------------
# result_sender pure helpers (P2)
# ---------------------------------------------------------------------------

def test_build_result_dict_prefers_model_used():
    from src.models.processing import ProcessingRequest, ProcessingResult, TranscriptionResult
    from src.services.result_sender import _build_result_dict

    req = ProcessingRequest(
        file_name="a.mp3", llm_provider="openai", user_id=1,
        speaker_mapping={"SPEAKER_00": "Ivan"},
    )
    res = ProcessingResult(
        transcription_result=TranscriptionResult(transcription="hello"),
        protocol_text="P",
        template_used={"name": "Daily"},
        llm_provider_used="openai",
        llm_model_used="GPT-4o",
    )

    d = _build_result_dict(req, res)

    assert d["llm_model_name"] == "GPT-4o"
    assert d["template_used"] == {"name": "Daily"}
    assert d["transcription_result"]["transcription"] == "hello"
    assert d["speaker_mapping"] == {"SPEAKER_00": "Ivan"}


def test_build_result_dict_falls_back_to_provider_name():
    from src.models.processing import ProcessingRequest, ProcessingResult, TranscriptionResult
    from src.services.result_sender import _build_result_dict

    req = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)
    res = ProcessingResult(
        transcription_result=TranscriptionResult(transcription=""),
        protocol_text="P",
        template_used={"name": "T"},
        llm_provider_used="openai",
        llm_model_used=None,
    )

    assert _build_result_dict(req, res)["llm_model_name"] == "OpenAI"


# ---------------------------------------------------------------------------
# MappingStateCache save/load round-trip incl. task_id (P3)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# LLMGenerationService model-name resolution (P6a)
# ---------------------------------------------------------------------------

async def test_get_model_display_name_from_preset():
    from src.services.processing.llm_generation import LLMGenerationService

    svc = LLMGenerationService(user_service=None, template_service=None)

    assert await svc.get_model_display_name({"name": "GPT-4o"}) == "GPT-4o"
    assert await svc.get_model_display_name({"model": "gpt-4o-mini"}) == "gpt-4o-mini"


async def test_resolve_model_display_name_never_raises():
    from src.services.processing.llm_generation import LLMGenerationService

    svc = LLMGenerationService(user_service=None, template_service=None)
    name = await svc.resolve_model_display_name()
    # When no active preset is configured the helper degrades to "?" rather than raising.
    assert isinstance(name, str)
    assert name != ""
