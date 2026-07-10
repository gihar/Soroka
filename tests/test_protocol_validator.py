"""Проверка использования диаризации в валидаторе протокола (#61).

check_diarization_usage раньше была мертва (return 1.0, []): её 10% веса в
оценке качества каждый протокол получал бесплатно. Здесь закрепляем оживлённую
семантику — проверка ищет в тексте протокола ИМЯ участника для сопоставленного
спикера и метку спикера (SPEAKER_N / S1) для несопоставленного, а также
считает упоминание имени сопоставленного участника в задачах указанием
ответственного.
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

import types  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from src.models.diarization import Diarization, Segment  # noqa: E402
from src.services.protocol_validator import ProtocolValidator  # noqa: E402


def _validator() -> ProtocolValidator:
    return ProtocolValidator()


def _diarization(*speakers: str) -> Diarization:
    """Диаризация с по одному сегменту на каждого переданного спикера."""
    return Diarization(
        segments=[Segment(speaker=s, text=f"реплика {s}") for s in speakers]
    )


# ==========================================================================
# Трассирующий тест: протокол, игнорирующий спикеров, теряет баллы
# ==========================================================================

def test_protocol_ignoring_speakers_scores_below_one():
    """Ни имени сопоставленного, ни метки несопоставленного в тексте → < 1.0 и рекомендации."""
    validator = _validator()
    diarization = _diarization("SPEAKER_1", "SPEAKER_2")

    score, suggestions = validator.check_diarization_usage(
        protocol={"discussion": "Обсудили бюджет и сроки без привязки к говорящим."},
        diarization=diarization,
        speaker_mapping={"SPEAKER_1": "Иван Петров"},
    )

    assert score < 1.0
    assert suggestions


# ==========================================================================
# Сопоставленный спикер: ищем ИМЯ участника, не метку
# ==========================================================================

def test_mapped_speaker_counted_by_name_without_label():
    """Имя сопоставленного в тексте, метки нет → спикер засчитан (нет «X из Y»)."""
    validator = _validator()
    diarization = _diarization("SPEAKER_1")

    _, suggestions = validator.check_diarization_usage(
        protocol={"discussion": "Мария представила отчёт по бюджету."},
        diarization=diarization,
        speaker_mapping={"SPEAKER_1": "Мария"},
    )

    # Метки SPEAKER_1 в тексте нет — засчёт доказывает поиск имени, а не метки.
    assert not any("из 1 спикеров" in s for s in suggestions)


def test_fully_used_mapped_speaker_scores_one():
    """Имя в обсуждении и в задачах → упоминание и ответственный на месте, оценка 1.0."""
    validator = _validator()
    diarization = _diarization("SPEAKER_1")

    score, suggestions = validator.check_diarization_usage(
        protocol={
            "discussion": "Иван Петров подвёл итоги.",
            "action_items": "Иван Петров готовит смету к пятнице.",
        },
        diarization=diarization,
        speaker_mapping={"SPEAKER_1": "Иван Петров"},
    )

    assert score == 1.0
    assert suggestions == []


# ==========================================================================
# Несопоставленный спикер: ищем метку как есть
# ==========================================================================

def test_unmapped_speaker_counted_by_underscore_label():
    """Нет сопоставления → метка SPEAKER_2 в тексте засчитывает спикера."""
    validator = _validator()
    diarization = _diarization("SPEAKER_2")

    _, suggestions = validator.check_diarization_usage(
        protocol={"discussion": "Реплику SPEAKER_2 занесли в решения."},
        diarization=diarization,
        speaker_mapping=None,
    )

    assert not any("из 1 спикеров" in s for s in suggestions)


def test_unmapped_speaker_counted_by_native_speechmatics_label():
    """Родная метка speechmatics S1 (без префикса SPEAKER_) тоже засчитывается."""
    validator = _validator()
    diarization = _diarization("S1")

    _, suggestions = validator.check_diarization_usage(
        protocol={"discussion": "Позицию S1 отразили в протоколе."},
        diarization=diarization,
        speaker_mapping={},
    )

    assert not any("из 1 спикеров" in s for s in suggestions)


# ==========================================================================
# Нейтральные случаи: без диаризации / без спикеров
# ==========================================================================

def test_no_diarization_is_neutral():
    """Диаризации нет → нейтрально (1.0, [])."""
    validator = _validator()

    score, suggestions = validator.check_diarization_usage(
        protocol={"discussion": "любой текст"},
        diarization=None,
        speaker_mapping={"SPEAKER_1": "Иван"},
    )

    assert score == 1.0
    assert suggestions == []


def test_empty_speakers_is_neutral():
    """Диаризация без сегментов (пустой speakers_text) → нейтрально (1.0, [])."""
    validator = _validator()

    score, suggestions = validator.check_diarization_usage(
        protocol={"discussion": "любой текст"},
        diarization=Diarization(segments=[]),
        speaker_mapping=None,
    )

    assert score == 1.0
    assert suggestions == []


# ==========================================================================
# Смесь: часть сопоставлена (ищем имя), часть нет (ищем метку)
# ==========================================================================

def test_mixed_mapping_counts_name_and_label_together():
    """Имя сопоставленного и метка несопоставленного в одном тексте — оба засчитаны."""
    validator = _validator()
    diarization = _diarization("SPEAKER_1", "SPEAKER_2")

    _, suggestions = validator.check_diarization_usage(
        protocol={"discussion": "Иван подвёл итоги, SPEAKER_2 задал вопрос."},
        diarization=diarization,
        speaker_mapping={"SPEAKER_1": "Иван"},
    )

    # Оба упомянуты (доля 1.0) → нет рекомендации о неполном охвате спикеров.
    assert not any("из 2 спикеров" in s for s in suggestions)


def test_mixed_mapping_penalizes_missing_speaker():
    """Сопоставленный по имени найден, несопоставленный по метке — нет: доля < 1.0."""
    validator = _validator()
    diarization = _diarization("SPEAKER_1", "SPEAKER_2")

    score, _ = validator.check_diarization_usage(
        protocol={"discussion": "Иван подвёл итоги встречи."},
        diarization=diarization,
        speaker_mapping={"SPEAKER_1": "Иван"},
    )

    # Один из двух спикеров без следа → оценка не дотягивает до идеальной.
    assert score < 1.0


# ==========================================================================
# Ответственные в задачах: имя сопоставленного и жёсткий регекс-fallback
# ==========================================================================

def test_mapped_name_in_tasks_counts_as_responsible():
    """Имя сопоставленного участника в задачах — указание ответственного (без маркера)."""
    validator = _validator()
    diarization = _diarization("SPEAKER_1")

    _, suggestions = validator.check_diarization_usage(
        protocol={
            "discussion": "Иван Петров подвёл итоги.",
            "action_items": "Иван Петров готовит смету.",
        },
        diarization=diarization,
        speaker_mapping={"SPEAKER_1": "Иван Петров"},
    )

    assert "Не указаны ответственные за задачи из числа спикеров" not in suggestions


def test_speaker_label_in_tasks_counts_as_responsible_fallback():
    """Для несопоставленного «спикер N» в задачах — регекс-fallback указания ответственного."""
    validator = _validator()
    diarization = _diarization("SPEAKER_1")

    _, suggestions = validator.check_diarization_usage(
        protocol={
            "discussion": "Обсуждение вёл SPEAKER_1.",
            "action_items": "Задачу выполнит спикер 1 до пятницы.",
        },
        diarization=diarization,
        speaker_mapping=None,
    )

    assert "Не указаны ответственные за задачи из числа спикеров" not in suggestions


# ==========================================================================
# Точка вызова: llm_generation прокидывает сопоставление в оценку качества,
# и вес проверки реально двигает protocol_quality_score в метриках обработки
# ==========================================================================

async def _run_generation(monkeypatch, *, protocol_body, generated_mapping, request_mapping):
    """Гоняет optimized_llm_generation с валидацией → (llm_result_data, метрики)."""
    import src.services.processing.llm_generation as llm_gen
    from src.llm import protocol_generator as generator
    from src.models.processing import ProcessingRequest, TranscriptionResult

    async def fake_generate(**kwargs):
        result = dict(protocol_body)
        if generated_mapping is not None:
            result["_speaker_mapping"] = dict(generated_mapping)
        result["_meeting_type"] = "status"
        return result

    monkeypatch.setattr(generator, "generate", fake_generate)
    monkeypatch.setattr(
        llm_gen, "resolve_active_preset",
        AsyncMock(return_value={"name": "T", "model": "m", "key": "k"}),
    )
    monkeypatch.setattr(llm_gen.settings, "enable_protocol_validation", True)
    monkeypatch.setattr(llm_gen.settings, "log_cache_metrics", False)

    service = llm_gen.LLMGenerationService(
        user_service=None,
        template_service=types.SimpleNamespace(
            extract_template_variables=lambda content: ["discussion", "action_items"]
        ),
    )
    transcription = TranscriptionResult(
        transcription="Иван Петров и Мария Сидорова обсудили бюджет и сроки проекта.",
        diarization=_diarization("SPEAKER_1", "SPEAKER_2"),
    )
    request = ProcessingRequest(
        file_name="a.mp3", llm_provider="openai", user_id=1,
        speaker_mapping=request_mapping,
    )
    metrics = types.SimpleNamespace()

    llm_result = await service.optimized_llm_generation(
        transcription, {"content": ""}, request, metrics,
    )
    return llm_result, metrics


_MAPPING = {"SPEAKER_1": "Иван Петров", "SPEAKER_2": "Мария Сидорова"}
_USES_SPEAKERS = {
    "discussion": "Иван Петров и Мария Сидорова согласовали бюджет.",
    "action_items": "Иван Петров готовит смету.",
}
_IGNORES_SPEAKERS = {
    "discussion": "Согласовали бюджет и сроки.",
    "action_items": "Подготовить смету.",
}


async def test_call_site_diarization_usage_moves_quality_score(monkeypatch):
    """Сопоставление из _speaker_mapping доходит до оценки: протокол с именами
    получает более высокий diarization_usage, и protocol_quality_score меняется."""
    used_result, used_metrics = await _run_generation(
        monkeypatch,
        protocol_body=_USES_SPEAKERS,
        generated_mapping=_MAPPING,
        request_mapping=None,
    )
    ignored_result, ignored_metrics = await _run_generation(
        monkeypatch,
        protocol_body=_IGNORES_SPEAKERS,
        generated_mapping=_MAPPING,
        request_mapping=None,
    )

    used_usage = used_result["_validation"]["scores"]["diarization_usage"]
    ignored_usage = ignored_result["_validation"]["scores"]["diarization_usage"]

    # request.speaker_mapping=None: имена нашлись только через _speaker_mapping.
    assert used_usage > ignored_usage
    assert ignored_usage < 1.0
    # Вес проверки реально двигает наблюдаемую метрику обработки.
    assert used_metrics.protocol_quality_score != ignored_metrics.protocol_quality_score


async def test_call_site_falls_back_to_request_mapping(monkeypatch):
    """Нет _speaker_mapping в результате генерации → берём request.speaker_mapping."""
    result, _ = await _run_generation(
        monkeypatch,
        protocol_body=_USES_SPEAKERS,
        generated_mapping=None,
        request_mapping=_MAPPING,
    )

    # Имена нашлись только если fallback на request.speaker_mapping сработал.
    assert result["_validation"]["scores"]["diarization_usage"] == 1.0
