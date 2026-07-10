"""Юнит-тесты value object «Диаризация» (#58).

Проверяют модель как единственный источник производных представлений
диаризации: список спикеров в порядке появления, тексты по спикерам,
форматированная транскрипция и сводка.
"""

from src.models.diarization import Diarization, Segment


def test_speakers_in_appearance_order_not_sorted():
    """Спикеры перечислены в порядке ПОЯВЛЕНИЯ в сегментах, а не отсортированы."""
    diar = Diarization(
        segments=[
            Segment(speaker="SPEAKER_2", text="раз", start=0.0, end=1.0),
            Segment(speaker="SPEAKER_1", text="два", start=1.0, end=2.0),
            Segment(speaker="SPEAKER_2", text="три", start=2.0, end=3.0),
        ]
    )

    assert diar.speakers == ["SPEAKER_2", "SPEAKER_1"]


def test_speakers_text_joins_per_speaker_across_segments():
    """Текст каждого спикера склеивается по всем его сегментам в порядке появления."""
    diar = Diarization(
        segments=[
            Segment(speaker="SPEAKER_1", text="привет", start=0.0, end=1.0),
            Segment(speaker="SPEAKER_2", text="здравствуй", start=1.0, end=2.0),
            Segment(speaker="SPEAKER_1", text="как дела", start=2.0, end=3.0),
        ]
    )

    assert diar.speakers_text == {
        "SPEAKER_1": "привет как дела",
        "SPEAKER_2": "здравствуй",
    }


def test_speakers_text_skips_empty_pieces_but_keeps_speaker_key():
    """Пустые реплики не попадают в склейку, но ключ спикера сохраняется (даже пустым)."""
    diar = Diarization(
        segments=[
            Segment(speaker="SPEAKER_1", text="", start=0.0, end=1.0),
            Segment(speaker="SPEAKER_1", text="  ", start=1.0, end=2.0),
            Segment(speaker="SPEAKER_2", text="слово", start=2.0, end=3.0),
        ]
    )

    assert diar.speakers_text == {"SPEAKER_1": "", "SPEAKER_2": "слово"}


def test_formatted_transcript_groups_only_consecutive_replicas():
    """Форматированная транскрипция группирует только ПОДРЯД идущие реплики спикера."""
    diar = Diarization(
        segments=[
            Segment(speaker="SPEAKER_1", text="привет", start=0.0, end=1.0),
            Segment(speaker="SPEAKER_1", text="как дела", start=1.0, end=2.0),
            Segment(speaker="SPEAKER_2", text="хорошо", start=2.0, end=3.0),
            Segment(speaker="SPEAKER_1", text="отлично", start=3.0, end=4.0),
        ]
    )

    assert diar.formatted_transcript == (
        "SPEAKER_1: привет как дела\n\nSPEAKER_2: хорошо\n\nSPEAKER_1: отлично"
    )


def test_speakers_summary_counts_words_per_speaker():
    """Сводка: «Общее количество говорящих: N» и построчно число слов каждого спикера."""
    diar = Diarization(
        segments=[
            Segment(speaker="SPEAKER_1", text="привет как дела", start=0.0, end=1.0),
            Segment(speaker="SPEAKER_2", text="всё хорошо", start=1.0, end=2.0),
        ]
    )

    assert diar.speakers_summary == (
        "Общее количество говорящих: 2\n\n"
        "SPEAKER_1: 3 слов\n"
        "SPEAKER_2: 2 слов\n"
    )


def test_empty_segments_yield_empty_derivations():
    """Пустой список сегментов даёт пустые производные и нулевую сводку."""
    diar = Diarization(segments=[])

    assert diar.speakers == []
    assert diar.speakers_text == {}
    assert diar.formatted_transcript == ""
    assert diar.speakers_summary == "Общее количество говорящих: 0\n\n"


def test_single_speaker_stays_one_group():
    """Один спикер: все реплики склеиваются в одну группу форматированного транскрипта."""
    diar = Diarization(
        segments=[
            Segment(speaker="SPEAKER_1", text="раз", start=0.0, end=1.0),
            Segment(speaker="SPEAKER_1", text="два", start=1.0, end=2.0),
        ]
    )

    assert diar.speakers == ["SPEAKER_1"]
    assert diar.formatted_transcript == "SPEAKER_1: раз два"


def test_segments_without_text_keep_speakers_but_no_formatted():
    """Сегменты без текста (напр. pyannote/picovoice): спикеры есть, форматирование пусто."""
    diar = Diarization(
        segments=[
            Segment(speaker="SPEAKER_2", text="", start=0.0, end=1.0),
            Segment(speaker="SPEAKER_1", text="", start=1.0, end=2.0),
        ]
    )

    assert diar.speakers == ["SPEAKER_2", "SPEAKER_1"]
    assert diar.speakers_text == {"SPEAKER_2": "", "SPEAKER_1": ""}
    assert diar.formatted_transcript == ""


def test_start_end_optional_default_to_none():
    """Тайминги опциональны: источник без них строит валидный сегмент."""
    diar = Diarization(segments=[Segment(speaker="SPEAKER_1", text="привет")])

    assert diar.segments[0].start is None
    assert diar.segments[0].end is None
    assert diar.segments[0].model_dump() == {
        "speaker": "SPEAKER_1", "text": "привет", "start": None, "end": None
    }
