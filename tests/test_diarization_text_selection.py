"""Характеризация четырёх точек выбора «форматированная или сырая» (#57).

Каждый потребитель диаризации сам решает, какой текст скормить дальше:
формат из диаризации или сырую транскрипцию. Правило у всех похоже, но живёт в
четырёх местах на голых dict-ах — #59 будет их консолидировать. Закрепляем
НАБЛЮДАЕМЫЙ выбор (какой текст реально уходит в промпт/препроцессор), а не
внутренние детали.

Все LLM/сеть замоканы через monkeypatch (автовосстановление глобалей — общий
suite остаётся зелёным). Приватные точки выбора зовём напрямую: они временные,
их поправит #59.
"""

import os
import sys
import types
from unittest.mock import AsyncMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

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
    """Есть formatted_transcript в диаризации → в промпт идёт он, не сырой текст."""
    service = _mapping_service()

    prompt = service._build_mapping_prompt(
        [], _PARTICIPANTS, "СЫРОЙ_ТЕКСТ",
        {"formatted_transcript": "ФОРМАТ_SPEAKER_1: реплика"},
    )

    assert "ФОРМАТ_SPEAKER_1: реплика" in prompt
    assert "СЫРОЙ_ТЕКСТ" not in prompt


def test_mapping_prompt_falls_back_to_raw_when_no_formatted():
    """Нет formatted_transcript → в промпт идёт сырая транскрипция."""
    service = _mapping_service()

    prompt = service._build_mapping_prompt([], _PARTICIPANTS, "СЫРОЙ_ТЕКСТ", {})

    assert "СЫРОЙ_ТЕКСТ" in prompt


def test_mapping_prompt_previews_long_text_unless_full_matching():
    """Длинный текст режется в превью; при full_text_matching идёт целиком."""
    service = _mapping_service()
    long_formatted = "СЛОВО " * 2000  # > 5000 символов → срабатывает превью

    preview_prompt = service._build_mapping_prompt(
        [], _PARTICIPANTS, "raw", {"formatted_transcript": long_formatted},
    )
    assert "=== СЕРЕДИНА ВСТРЕЧИ ===" in preview_prompt

    service.full_text_matching = True
    full_prompt = service._build_mapping_prompt(
        [], _PARTICIPANTS, "raw", {"formatted_transcript": long_formatted},
    )
    assert "=== СЕРЕДИНА ВСТРЕЧИ ===" not in full_prompt
    assert long_formatted.strip() in full_prompt


# ==========================================================================
# Точка 2: выбор текста анализа в двухэтапной генерации
#          protocol_generator._generate_two_stage (analysis_transcription)
# ==========================================================================

async def _run_two_stage(monkeypatch, *, transcription, diarization_data):
    """Гоняет _generate_two_stage с замоканным вызовом модели, вернёт промпт генерации."""
    from src.llm import protocol_generator as generator

    calls = []

    async def fake_call(**kwargs):
        calls.append(kwargs)
        return {"protocol_data": {}, "quality_score": 0.0}

    monkeypatch.setattr(generator, "_call_openai", fake_call)

    # Пропускаем ЭТАП 1, задав тип и маппинг: analysis_transcription всё равно
    # уходит в промпт ЭТАПА 2 — по нему и характеризуем выбор.
    await generator._generate_two_stage(
        preset=None,
        transcription=transcription,
        template_variables={},
        diarization_data=diarization_data,
        meeting_type="technical",
        speaker_mapping={"SPEAKER_1": "Иван Иванов"},
    )
    generation = next(c for c in calls if c.get("step_name") == "Generation")
    return generation["user_prompt"]


async def test_analysis_uses_formatted_transcript_from_diarization(monkeypatch):
    """diarization_data.formatted_transcript присутствует → он идёт в анализ/генерацию."""
    prompt = await _run_two_stage(
        monkeypatch,
        transcription="СЫРОЙ_АНАЛИЗ",
        diarization_data={"formatted_transcript": "ФОРМ_АНАЛИЗ SPEAKER_1"},
    )

    assert "ФОРМ_АНАЛИЗ SPEAKER_1" in prompt
    assert "СЫРОЙ_АНАЛИЗ" not in prompt


async def test_analysis_falls_back_to_raw_transcription(monkeypatch):
    """Нет диаризации → в анализ/генерацию идёт сырая транскрипция."""
    prompt = await _run_two_stage(
        monkeypatch, transcription="СЫРОЙ_АНАЛИЗ", diarization_data=None,
    )

    assert "СЫРОЙ_АНАЛИЗ" in prompt


async def test_analysis_falls_back_when_formatted_key_empty(monkeypatch):
    """Ключ есть, но пустой → тоже откат на сырую транскрипцию."""
    prompt = await _run_two_stage(
        monkeypatch,
        transcription="СЫРОЙ_АНАЛИЗ",
        diarization_data={"formatted_transcript": ""},
    )

    assert "СЫРОЙ_АНАЛИЗ" in prompt


# ==========================================================================
# Точка 3: выбор текста в LLM-генерации протокола
#          llm_generation.optimized_llm_generation
# ==========================================================================

async def _capture_generate_transcription(monkeypatch, *, diarization, formatted, raw):
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
    result = TranscriptionResult(
        transcription=raw, diarization=diarization, formatted_transcript=formatted,
    )
    request = ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1)

    await service.optimized_llm_generation(
        result, {"content": ""}, request, types.SimpleNamespace(),
    )
    return captured["transcription"]


async def test_llm_generation_uses_formatted_when_diarization_present(monkeypatch):
    """Диаризация есть и formatted_transcript непуст → в generate идёт форматированный."""
    transcription = await _capture_generate_transcription(
        monkeypatch, diarization={"segments": [1]},
        formatted="ФОРМ_ТРАНСКРИПТ", raw="СЫРОЙ",
    )

    assert transcription == "ФОРМ_ТРАНСКРИПТ"


async def test_llm_generation_uses_raw_when_no_diarization(monkeypatch):
    """Диаризации нет → formatted игнорируется, в generate идёт сырой текст."""
    transcription = await _capture_generate_transcription(
        monkeypatch, diarization=None,
        formatted="ФОРМ_ТРАНСКРИПТ", raw="СЫРОЙ",
    )

    assert transcription == "СЫРОЙ"


# ==========================================================================
# Точка 4: предобработка текста читает formatted_transcript через getattr
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
        def preprocess(self, text, formatted_transcript):
            captured["text"] = text
            captured["formatted_transcript"] = formatted_transcript
            return {
                "cleaned_text": f"{text}_C",
                "cleaned_formatted": f"{formatted_transcript}_F" if formatted_transcript else "",
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


async def test_preprocessing_reads_formatted_transcript_from_result(monkeypatch):
    """Препроцессор получает formatted_transcript из результата и сырой transcription."""
    result = TranscriptionResult(
        transcription="СЫРОЙ", diarization={"total_speakers": 2},
        formatted_transcript="ФОРМ",
    )

    captured, _ = await _run_preprocessing(monkeypatch, result)

    assert captured["text"] == "СЫРОЙ"
    assert captured["formatted_transcript"] == "ФОРМ"


async def test_preprocessing_writes_cleaned_text_back(monkeypatch):
    """Очищенные тексты кладутся обратно в transcription/formatted_transcript."""
    result = TranscriptionResult(
        transcription="СЫРОЙ", diarization={"total_speakers": 2},
        formatted_transcript="ФОРМ",
    )

    _, out = await _run_preprocessing(monkeypatch, result)

    assert out.transcription == "СЫРОЙ_C"
    assert out.formatted_transcript == "ФОРМ_F"
