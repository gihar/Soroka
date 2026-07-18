"""Выбор «форматированная или сырая» после консолидации в best_transcript (#59).

До #59 каждый потребитель диаризации сам решал, какой текст скормить дальше:
формат из диаризации или сырую транскрипцию — правило жило в четырёх местах на
голых dict-ах. #59 свёл выбор в единое свойство `TranscriptionResult.best_transcript`
(его плечи проверяет test_best_transcript). Здесь остаётся закрепить, что
потребители читают ГОТОВЫЙ текст:

- промпт сопоставления берёт форматированную транскрипцию из типизированной
  диаризации, иначе — сырой текст (точка 1, поведение сохранено);
- двухэтапная генерация больше не выбирает текст сама — ведёт ГОТОВЫЙ transcription
  в промпт (точка 2, выбор вынесен в best_transcript);
- LLM-генерация протокола ведёт в generate() именно best_transcript (точка 3);
- предобработка чистит сырую транскрипцию; форматированного дубля больше нет,
  round-trip убран вместе с полем (точка 4).

Все LLM/сеть замоканы через monkeypatch. Приватные точки зовём напрямую.
"""

import os
import sys
import types
from unittest.mock import AsyncMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

from src.models.diarization import Diarization, Segment  # noqa: E402
from src.models.processing import ProcessingRequest, TranscriptionResult  # noqa: E402

# ==========================================================================
# Точка 1: источник транскрипта для промпта сопоставления спикеров
#          speaker_mapping_service._build_mapping_prompt
# ==========================================================================

def _mapping_service():
    from src.services.speaker_mapping_service import SpeakerMappingService

    service = SpeakerMappingService()
    service.full_text_matching = False
    return service


_PARTICIPANTS = [{"name": "Иван Иванов", "role": "PM"}]


def test_mapping_prompt_uses_formatted_transcript_when_present():
    """Есть диаризация с форматом → в промпт идёт он, не сырой текст."""
    service = _mapping_service()
    diarization = Diarization(segments=[Segment(speaker="SPEAKER_1", text="реплика")])

    prompt = service._build_mapping_prompt([], _PARTICIPANTS, "СЫРОЙ_ТЕКСТ", diarization)

    assert "SPEAKER_1: реплика" in prompt
    assert "СЫРОЙ_ТЕКСТ" not in prompt


def test_mapping_prompt_falls_back_to_raw_when_no_diarization():
    """Нет диаризации → в промпт идёт сырая транскрипция."""
    service = _mapping_service()

    prompt = service._build_mapping_prompt([], _PARTICIPANTS, "СЫРОЙ_ТЕКСТ", None)

    assert "СЫРОЙ_ТЕКСТ" in prompt


def test_mapping_prompt_previews_long_text_unless_full_matching():
    """Длинный текст режется в превью; при full_text_matching идёт целиком."""
    service = _mapping_service()
    # Один спикер с длинной репликой → formatted_transcript > 5000 символов.
    diarization = Diarization(
        segments=[Segment(speaker="SPEAKER_1", text="СЛОВО " * 2000)]
    )

    preview_prompt = service._build_mapping_prompt(
        [], _PARTICIPANTS, "raw", diarization,
    )
    assert "=== СЕРЕДИНА ВСТРЕЧИ ===" in preview_prompt

    service.full_text_matching = True
    full_prompt = service._build_mapping_prompt(
        [], _PARTICIPANTS, "raw", diarization,
    )
    assert "=== СЕРЕДИНА ВСТРЕЧИ ===" not in full_prompt
    assert diarization.formatted_transcript in full_prompt


# ==========================================================================
# Точка 2: двухэтапная генерация ведёт ГОТОВЫЙ transcription в промпт
#          protocol_generator._generate_two_stage
# ==========================================================================

async def test_two_stage_forwards_given_transcription_to_generation(monkeypatch):
    """_generate_two_stage не выбирает текст сам — ведёт свой transcription в промпт."""
    from src.llm import protocol_generator as generator

    calls = []

    async def fake_call(**kwargs):
        calls.append(kwargs)
        return {"protocol_data": {}, "quality_score": 0.0}

    monkeypatch.setattr(generator, "_call_openai", fake_call)

    await generator._generate_two_stage(
        preset=None,
        transcription="ГОТОВЫЙ_ТЕКСТ",
        template_variables={},
        meeting_type="technical",
        speaker_mapping={"SPEAKER_1": "Иван Иванов"},
    )
    generation = next(c for c in calls if c.get("step_name") == "Generation")
    assert "ГОТОВЫЙ_ТЕКСТ" in generation["user_prompt"]


# ==========================================================================
# Точка 3: LLM-генерация протокола ведёт в generate() именно best_transcript
#          llm_generation.optimized_llm_generation
# ==========================================================================

async def _capture_generate_transcription(monkeypatch, *, diarization, raw):
    """Гоняет optimized_llm_generation, вернёт transcription, ушедший в generate()."""
    import src.services.processing.llm_generation as llm_gen
    from src.llm import protocol_generator as generator

    captured = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(generator, "generate", fake_generate)
    monkeypatch.setattr(
        llm_gen, "resolve_active_preset",
        AsyncMock(return_value={"name": "T", "model": "m", "key": "k"}),
    )
    monkeypatch.setattr(llm_gen.settings, "enable_protocol_validation", False)
    monkeypatch.setattr(llm_gen.settings, "log_cache_metrics", False)

    service = llm_gen.LLMGenerationService(
        user_service=None,
        template_service=types.SimpleNamespace(extract_template_variables=lambda c: []),
    )
    result = TranscriptionResult(transcription=raw, diarization=diarization)
    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)

    await service.optimized_llm_generation(
        result, {"content": ""}, request, types.SimpleNamespace(),
    )
    return captured["transcription"]


async def test_llm_generation_uses_formatted_when_diarization_present(monkeypatch):
    """Диаризация есть → в generate идёт её форматированный текст (best_transcript)."""
    diarization = Diarization(segments=[Segment(speaker="SPEAKER_1", text="реплика")])

    transcription = await _capture_generate_transcription(
        monkeypatch, diarization=diarization, raw="СЫРОЙ",
    )

    assert transcription == diarization.formatted_transcript


async def test_llm_generation_uses_raw_when_no_diarization(monkeypatch):
    """Диаризации нет → в generate идёт сырой текст (best_transcript)."""
    transcription = await _capture_generate_transcription(
        monkeypatch, diarization=None, raw="СЫРОЙ",
    )

    assert transcription == "СЫРОЙ"


# ==========================================================================
# Точка 4: предобработка чистит сырую транскрипцию (форматированного дубля нет)
#          processing_service._optimized_transcription
# ==========================================================================

async def _run_preprocessing(monkeypatch, result):
    """Гоняет _optimized_transcription (кэш/транскрипция замоканы), вернёт (аргументы preprocess, итог)."""
    import src.services.processing.processing_service as pss

    service = pss.ProcessingService.__new__(pss.ProcessingService)
    service._calculate_file_hash = AsyncMock(return_value="hash")
    service._run_transcription_async = AsyncMock(return_value=result)

    class _Cache:
        async def get(self, key):
            return None

        async def set(self, *args, **kwargs):
            return None

    captured = {}

    class _Preprocessor:
        def preprocess(self, text, formatted_transcript=None):
            captured["text"] = text
            captured["formatted_transcript"] = formatted_transcript
            return {
                "cleaned_text": f"{text}_C",
                "cleaned_formatted": "",
                "statistics": {"reduction_percent": 0},
            }

    monkeypatch.setattr(pss, "performance_cache", _Cache())
    monkeypatch.setattr(pss, "get_preprocessor", lambda language: _Preprocessor())
    monkeypatch.setattr(pss.settings, "enable_text_preprocessing", True)

    request = ProcessingRequest(
        file_name="a.mp3", llm_provider="openai", user_id=1, language="ru",
    )
    out = await service._optimized_transcription("f.mp3", request, types.SimpleNamespace())
    return captured, out


async def test_preprocessing_reads_raw_transcription(monkeypatch):
    """Препроцессор получает сырую transcription; форматированный текст ему не передаётся."""
    result = TranscriptionResult(
        transcription="СЫРОЙ",
        diarization=Diarization(segments=[Segment(speaker="SPEAKER_1", text="реплика")]),
    )

    captured, _ = await _run_preprocessing(monkeypatch, result)

    assert captured["text"] == "СЫРОЙ"
    assert captured["formatted_transcript"] is None


async def test_preprocessing_writes_cleaned_text_back(monkeypatch):
    """Очищенный текст кладётся обратно в transcription; отдельного formatted-поля нет."""
    result = TranscriptionResult(
        transcription="СЫРОЙ",
        diarization=Diarization(segments=[Segment(speaker="SPEAKER_1", text="реплика")]),
    )

    _, out = await _run_preprocessing(monkeypatch, result)

    assert out.transcription == "СЫРОЙ_C"
    assert not hasattr(out, "formatted_transcript")
