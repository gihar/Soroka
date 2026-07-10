"""Характеризация форм payload диаризации по бэкендам транскрипции (#57).

Страховка перед типизацией «Диаризации» (#58): фиксирует, ЧТО именно кладёт
каждый бэкенд в dict диаризации и в top-level поля TranscriptionResult, пока
это всё живёт на голых словарях. Прод-код не меняется.

Мок не нужен — обрабатывающие методы (`to_dict`, `_process_transcript_result`)
чистые: не ходят в сеть и не читают self. Инстансы создаём через `__new__`,
минуя тяжёлую инициализацию клиентов.

Разведанные асимметрии, закреплённые здесь как «текущее поведение»:
- локальный путь кладёт в dict ТОЛЬКО segments/speakers/total_speakers;
- deepgram дополнительно кладёт formatted_transcript/speakers_text и нормализует
  метки в SPEAKER_N по порядку появления;
- speechmatics всегда отдаёт diarization=None, тексты — только в top-level,
  метки спикеров РОДНЫЕ (S1/S2, не SPEAKER_N), порядок спикеров недетерминирован
  (собирается из set()).
"""

from src.services.deepgram_service import DeepgramService
from src.services.diarization_service import DiarizationResult
from src.services.speechmatics_service import SpeechmaticsService


# --------------------------------------------------------------------------
# Локальный путь: whisperx+pyannote → DiarizationResult.to_dict()
# --------------------------------------------------------------------------

def _local_result() -> DiarizationResult:
    return DiarizationResult(
        segments=[
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_1", "text": "привет"},
            {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_2", "text": "здравствуй"},
            {"start": 4.0, "end": 5.0, "speaker": "SPEAKER_1", "text": "как дела"},
        ],
        speakers=["SPEAKER_1", "SPEAKER_2"],
    )


def test_local_to_dict_carries_only_three_keys():
    """Локальный dict диаризации — ровно {segments, speakers, total_speakers}."""
    payload = _local_result().to_dict()

    assert set(payload.keys()) == {"segments", "speakers", "total_speakers"}
    assert payload["speakers"] == ["SPEAKER_1", "SPEAKER_2"]
    assert payload["total_speakers"] == 2


def test_local_to_dict_omits_formatted_and_speakers_text():
    """Характеризация: formatted_transcript/speakers_text В dict НЕ кладутся.

    В отличие от deepgram, локальный путь держит их отдельно — top-level поля
    TranscriptionResult заполняет `_ensure_diarization`, вызывая отдельные методы.
    """
    payload = _local_result().to_dict()

    assert "formatted_transcript" not in payload
    assert "speakers_text" not in payload


def test_local_formatted_and_speakers_text_come_from_separate_methods():
    """Форматированный транскрипт и тексты спикеров — отдельные методы, не dict."""
    result = _local_result()

    assert result.get_formatted_transcript() == (
        "SPEAKER_1: привет\n\nSPEAKER_2: здравствуй\n\nSPEAKER_1: как дела"
    )
    # Текст спикера склеивается по всем его сегментам в порядке появления.
    assert result.get_speakers_text() == {
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
