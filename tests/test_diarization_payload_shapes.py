"""Адаптеры бэкендов кладут в результат типизированную «Диаризацию» (#59).

Изначально (#57/#58/#60) файл пинил переходную dict-форму диаризации на
результате транскрипции. #59 убрал эту форму: `TranscriptionResult.diarization`
несёт сам объект `Diarization`, top-level дублей нет. Внутренняя нормализация
меток и вывод производных проверяются контрактом (test_diarization_contract) и
моделью (test_diarization_model); здесь остаётся уникальное — СТЫК адаптера
`_process_transcript_result` (сырой ответ бэкенда → TranscriptionResult):
включённая диаризация даёт объект, выключенная — None и сырой текст.

Мок не нужен — методы чистые: не ходят в сеть и не читают тяжёлый self.
Инстансы сервисов создаём через `__new__`.
"""

from src.models.diarization import Diarization
from src.services.deepgram_service import DeepgramService
from src.services.speechmatics_service import SpeechmaticsService


# --------------------------------------------------------------------------
# Deepgram: _process_transcript_result → TranscriptionResult с объектом
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


def test_deepgram_result_carries_diarization_object():
    """При диаризации адаптер кладёт в поле сам `Diarization`, а не dict."""
    result = _process_deepgram(_deepgram_response(), enable_diarization=True)

    assert isinstance(result.diarization, Diarization)
    # Сырые id (0,1) нормализованы в SPEAKER_N по порядку появления.
    assert result.diarization.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert [(s.speaker, s.text) for s in result.diarization.segments] == [
        ("SPEAKER_1", "привет"),
        ("SPEAKER_2", "как дела"),
        ("SPEAKER_1", "всё хорошо"),
    ]


def test_deepgram_without_diarization_yields_none_and_raw_transcription():
    """Без диаризации diarization=None; сырой текст — best_transcript."""
    result = _process_deepgram(_deepgram_response(), enable_diarization=False)

    assert result.diarization is None
    assert result.transcription == "привет как дела всё хорошо"
    assert result.best_transcript == "привет как дела всё хорошо"


# --------------------------------------------------------------------------
# Speechmatics: _process_transcript_result → TranscriptionResult с объектом
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


def test_speechmatics_result_carries_diarization_object_with_native_labels():
    """Метки спикеров РОДНЫЕ (S1/S2, не SPEAKER_N), в поле — сам объект."""
    result = _process_speechmatics(_speechmatics_transcript(), enable_diarization=True)

    assert isinstance(result.diarization, Diarization)
    assert result.diarization.speakers == ["S1", "S2"]
    assert [(s.speaker, s.text) for s in result.diarization.segments] == [
        ("S1", "привет мир"),
        ("S2", "ага"),
    ]


def test_speechmatics_without_diarization_yields_none_and_raw_transcription():
    """Без диаризации diarization=None; сырой текст — best_transcript."""
    result = _process_speechmatics(_speechmatics_transcript(), enable_diarization=False)

    assert result.diarization is None
    assert result.transcription == "привет мир ага"
    assert result.best_transcript == "привет мир ага"
