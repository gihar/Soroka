"""Формы payload диаризации по бэкендам транскрипции (обновлено для #58).

Изначально (#57) фиксировало ЧТО кладёт каждый бэкенд, пока диаризация жила на
голых словарях. #58 ввёл единый value object «Диаризация»: локальный путь и
deepgram теперь дают ОДИН и тот же `to_dict()` с пятью ключами. Speechmatics —
НЕ трогали, поэтому его характеризация оставлена как есть.

Мок не нужен — обрабатывающие методы (`to_dict`, `_process_transcript_result`)
чистые: не ходят в сеть и не читают тяжёлый self. Инстансы сервисов создаём
через `__new__`.

Формы, закреплённые здесь:
- локальный путь строит «Диаризацию» и кладёт её единый to_dict (пять ключей);
- deepgram строит ту же «Диаризацию»; нормализация меток в SPEAKER_N по порядку
  появления осталась на уровне адаптера, форма dict совпадает с локальной;
- speechmatics по-прежнему отдаёт diarization=None, тексты — только в top-level,
  метки спикеров РОДНЫЕ (S1/S2, не SPEAKER_N), порядок спикеров недетерминирован
  (собирается из set()).
"""

from src.services.deepgram_service import DeepgramService
from src.services.diarization_service import build_diarization_from_segments
from src.services.speechmatics_service import SpeechmaticsService


# --------------------------------------------------------------------------
# Локальный путь: whisperx/pyannote → build_diarization_from_segments → to_dict()
# --------------------------------------------------------------------------

def _local_diarization():
    return build_diarization_from_segments([
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_1", "text": "привет"},
        {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_2", "text": "здравствуй"},
        {"start": 4.0, "end": 5.0, "speaker": "SPEAKER_1", "text": "как дела"},
    ])


def test_local_to_dict_is_unified_five_key_shape():
    """#58: локальный dict диаризации — единая форма с пятью ключами."""
    payload = _local_diarization().to_dict()

    assert set(payload.keys()) == {
        "segments", "speakers", "total_speakers",
        "formatted_transcript", "speakers_text",
    }
    assert payload["speakers"] == ["SPEAKER_1", "SPEAKER_2"]
    assert payload["total_speakers"] == 2


def test_local_to_dict_now_carries_formatted_and_speakers_text():
    """#58: локальный путь СНОВА кладёт formatted_transcript/speakers_text В dict.

    До #58 их держали отдельно; теперь единый to_dict несёт их наравне с deepgram,
    поэтому dict-читатели (например промпт сопоставления) получают форматированный
    текст и на локальном пути.
    """
    payload = _local_diarization().to_dict()

    assert payload["formatted_transcript"] == (
        "SPEAKER_1: привет\n\nSPEAKER_2: здравствуй\n\nSPEAKER_1: как дела"
    )
    # Текст спикера склеивается по всем его сегментам в порядке появления.
    assert payload["speakers_text"] == {
        "SPEAKER_1": "привет как дела",
        "SPEAKER_2": "здравствуй",
    }


# --------------------------------------------------------------------------
# Deepgram: _process_transcript_result → dict С formatted/speakers_text
# --------------------------------------------------------------------------

def _deepgram_response() -> dict:
    """Сырой JSON deepgram: один канал + utterances с чередованием спикеров."""
    return {
        "results": {
            "channels": [
                {"alternatives": [{"transcript": "привет как дела всё хорошо"}]}
            ],
            "utterances": [
                {"speaker": 0, "transcript": "привет", "start": 0.0, "end": 1.0},
                {"speaker": 1, "transcript": "как дела", "start": 1.0, "end": 2.5},
                {"speaker": 0, "transcript": "всё хорошо", "start": 2.5, "end": 3.2},
            ],
        }
    }


def _process_deepgram(response, enable_diarization):
    service = DeepgramService.__new__(DeepgramService)
    return service._process_transcript_result(response, enable_diarization)


def test_deepgram_dict_carries_formatted_and_speakers_text():
    """Deepgram кладёт В dict пять ключей, включая formatted_transcript/speakers_text."""
    result = _process_deepgram(_deepgram_response(), enable_diarization=True)

    assert set(result.diarization.keys()) == {
        "segments", "speakers", "total_speakers",
        "formatted_transcript", "speakers_text",
    }


def test_deepgram_labels_are_sequential_speaker_n_in_appearance_order():
    """Сырые id спикеров (0,1) нормализуются в SPEAKER_N по порядку появления."""
    result = _process_deepgram(_deepgram_response(), enable_diarization=True)
    diar = result.diarization

    assert diar["speakers"] == ["SPEAKER_1", "SPEAKER_2"]
    assert diar["total_speakers"] == 2
    # Каждый сегмент несёт speaker/start/end/text.
    assert diar["segments"] == [
        {"speaker": "SPEAKER_1", "start": 0.0, "end": 1.0, "text": "привет"},
        {"speaker": "SPEAKER_2", "start": 1.0, "end": 2.5, "text": "как дела"},
        {"speaker": "SPEAKER_1", "start": 2.5, "end": 3.2, "text": "всё хорошо"},
    ]


def test_deepgram_speakers_text_accumulates_across_utterances():
    """Реплики одного спикера склеиваются в speakers_text по порядку."""
    result = _process_deepgram(_deepgram_response(), enable_diarization=True)

    assert result.diarization["speakers_text"] == {
        "SPEAKER_1": "привет всё хорошо",
        "SPEAKER_2": "как дела",
    }
    # formatted_transcript сохраняет чередование реплик, а не «весь текст спикера».
    assert result.diarization["formatted_transcript"] == (
        "SPEAKER_1: привет\n\nSPEAKER_2: как дела\n\nSPEAKER_1: всё хорошо"
    )


def test_deepgram_top_level_mirrors_diarization_dict():
    """top-level formatted/speakers_text заполнены теми же значениями, что в dict."""
    result = _process_deepgram(_deepgram_response(), enable_diarization=True)

    assert result.formatted_transcript == result.diarization["formatted_transcript"]
    assert result.speakers_text == result.diarization["speakers_text"]


def test_deepgram_without_diarization_yields_none_and_raw_formatted():
    """Без диаризации diarization=None, formatted_transcript == сырой текст."""
    result = _process_deepgram(_deepgram_response(), enable_diarization=False)

    assert result.diarization is None
    assert result.formatted_transcript == "привет как дела всё хорошо"
    assert result.speakers_text == {}


# --------------------------------------------------------------------------
# Speechmatics: _process_transcript_result → diarization=None, тексты в top-level
# --------------------------------------------------------------------------

def _speechmatics_transcript() -> dict:
    """json-v2: слова со спикерами; смена спикера рвёт сегмент."""
    return {
        "results": [
            {"type": "word", "start_time": 0.0, "end_time": 0.5,
             "alternatives": [{"content": "привет", "speaker": "S1"}]},
            {"type": "word", "start_time": 0.5, "end_time": 1.0,
             "alternatives": [{"content": "мир", "speaker": "S1"}]},
            {"type": "word", "start_time": 1.0, "end_time": 1.6,
             "alternatives": [{"content": "ага", "speaker": "S2"}]},
        ]
    }


def _process_speechmatics(transcript, enable_diarization):
    service = SpeechmaticsService.__new__(SpeechmaticsService)
    return service._process_transcript_result(transcript, enable_diarization)


def test_speechmatics_diarization_is_always_none():
    """Характеризация: speechmatics НИКОГДА не отдаёт отдельный dict диаризации."""
    result = _process_speechmatics(_speechmatics_transcript(), enable_diarization=True)

    assert result.diarization is None


def test_speechmatics_native_texts_only_in_top_level():
    """Форматированный транскрипт и тексты спикеров живут только в top-level полях."""
    result = _process_speechmatics(_speechmatics_transcript(), enable_diarization=True)

    assert result.transcription == "привет мир ага"
    assert result.formatted_transcript == "S1: привет мир\n\nS2: ага"


def test_speechmatics_keeps_native_speaker_labels_not_speaker_n():
    """Метки спикеров — РОДНЫЕ (S1/S2), speechmatics их не нормализует в SPEAKER_N."""
    result = _process_speechmatics(_speechmatics_transcript(), enable_diarization=True)

    # Инвариант состава множества: порядок недетерминирован (собирается из set()),
    # поэтому фиксируем набор ключей и значения, а не их последовательность.
    assert set(result.speakers_text.keys()) == {"S1", "S2"}
    assert result.speakers_text["S1"] == "привет мир"
    assert result.speakers_text["S2"] == "ага"


def test_speechmatics_without_diarization_has_no_speakers_text():
    """Без диаризации speakers_text пуст, formatted == сырой текст."""
    result = _process_speechmatics(_speechmatics_transcript(), enable_diarization=False)

    assert result.diarization is None
    assert result.formatted_transcript == "привет мир ага"
    assert result.speakers_text == {}
