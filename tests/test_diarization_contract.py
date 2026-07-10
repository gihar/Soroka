"""Контракт «Диаризации» по источникам (#58).

Все источники диаризации (локальный whisperx/pyannote, deepgram, picovoice)
строят ОДИН value object `Diarization` с одинаковыми гарантиями. Тест
параметризован по источникам: каждый берёт свою сырую форму, прогоняет её через
свой адаптер-строитель и обязан дать `Diarization`, удовлетворяющую единому
контракту.

Сеть/модели не нужны: адаптеры-строители чистые (сегменты → Diarization),
инстансы сервисов создаём через `__new__`, минуя тяжёлую инициализацию.
"""

import types

import pytest

from src.models.diarization import Diarization
from src.utils.transcript_formatter import format_transcript_with_speaker_sequence


# --------------------------------------------------------------------------
# Источники: каждая функция даёт (Diarization, ожидаемые_спикеры, есть_ли_текст)
# --------------------------------------------------------------------------

def _local_source():
    """Локальный путь: whisperx/pyannote отдают сегменты speaker/text/start/end."""
    from src.services.diarization_service import build_diarization_from_segments

    raw_segments = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_2", "text": "привет"},
        {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_1", "text": "здравствуй"},
        {"start": 4.0, "end": 5.0, "speaker": "SPEAKER_2", "text": "как дела"},
    ]
    return build_diarization_from_segments(raw_segments), ["SPEAKER_2", "SPEAKER_1"], True


def _deepgram_source():
    """Deepgram: сырые utterances нормализуются в SPEAKER_N по порядку появления."""
    from src.services.deepgram_service import DeepgramService

    utterances = [
        {"speaker": 0, "transcript": "привет", "start": 0.0, "end": 1.0},
        {"speaker": 1, "transcript": "как дела", "start": 1.0, "end": 2.5},
        {"speaker": 0, "transcript": "всё хорошо", "start": 2.5, "end": 3.2},
    ]
    service = DeepgramService.__new__(DeepgramService)
    return service._build_diarization(utterances), ["SPEAKER_1", "SPEAKER_2"], True


def _picovoice_source():
    """Picovoice Falcon: сегменты с тегами спикеров, но без текста (текст позже)."""
    from src.services.picovoice_service import PicovoiceService

    falcon_segments = [
        types.SimpleNamespace(speaker_tag=2, start_sec=0.0, end_sec=1.0),
        types.SimpleNamespace(speaker_tag=1, start_sec=1.0, end_sec=2.0),
        types.SimpleNamespace(speaker_tag=2, start_sec=2.0, end_sec=3.0),
    ]
    service = PicovoiceService.__new__(PicovoiceService)
    return service._parse_falcon_result(falcon_segments), ["SPEAKER_2", "SPEAKER_1"], False


_SOURCES = {
    "local": _local_source,
    "deepgram": _deepgram_source,
    "picovoice": _picovoice_source,
}


@pytest.fixture(params=list(_SOURCES), ids=list(_SOURCES))
def source(request):
    diar, expected_speakers, has_text = _SOURCES[request.param]()
    return diar, expected_speakers, has_text


# --------------------------------------------------------------------------
# Единый контракт
# --------------------------------------------------------------------------

def test_source_builds_diarization_instance(source):
    """Любой источник возвращает именно `Diarization`."""
    diar, _, _ = source

    assert isinstance(diar, Diarization)


def test_segments_carry_speaker_text_and_timings(source):
    """Каждый сегмент несёт speaker/text (строки) и start/end (float или None)."""
    diar, _, _ = source

    assert diar.segments  # источник дал непустой набор
    for segment in diar.segments:
        assert isinstance(segment.speaker, str) and segment.speaker
        assert isinstance(segment.text, str)
        assert segment.start is None or isinstance(segment.start, float)
        assert segment.end is None or isinstance(segment.end, float)


def test_speakers_are_unique_in_appearance_order(source):
    """Спикеры уникальны и идут в порядке первого появления в сегментах."""
    diar, expected_speakers, _ = source

    assert diar.speakers == expected_speakers
    assert len(diar.speakers) == len(set(diar.speakers))

    first_seen = []
    for segment in diar.segments:
        if segment.speaker not in first_seen:
            first_seen.append(segment.speaker)
    assert diar.speakers == first_seen


def test_derived_fields_consistent_with_segments(source):
    """speakers_text и formatted_transcript выводятся из тех же сегментов."""
    diar, _, _ = source

    expected_formatted = format_transcript_with_speaker_sequence(
        [segment.model_dump() for segment in diar.segments]
    )
    assert diar.formatted_transcript == expected_formatted

    # speakers_text: ключи совпадают со спикерами, значения — склейка их реплик.
    assert set(diar.speakers_text.keys()) == set(diar.speakers)
    for speaker in diar.speakers:
        expected = " ".join(
            s.text.strip() for s in diar.segments
            if s.speaker == speaker and s.text.strip()
        )
        assert diar.speakers_text[speaker] == expected


def test_text_carrying_sources_fill_formatted_and_texts(source):
    """Источники с текстом дают непустые formatted_transcript и speakers_text."""
    diar, _, has_text = source
    if not has_text:
        pytest.skip("источник без текста (текст добавляется отдельно)")

    assert diar.formatted_transcript
    assert any(diar.speakers_text.values())


def test_to_dict_is_unified_five_key_shape(source):
    """`to_dict()` у любого источника — единая форма с пятью ключами."""
    diar, _, _ = source

    payload = diar.to_dict()
    assert set(payload.keys()) == {
        "segments", "speakers", "total_speakers",
        "formatted_transcript", "speakers_text",
    }
    assert payload["speakers"] == diar.speakers
    assert payload["total_speakers"] == len(diar.speakers)
    assert payload["formatted_transcript"] == diar.formatted_transcript
    assert payload["speakers_text"] == diar.speakers_text
