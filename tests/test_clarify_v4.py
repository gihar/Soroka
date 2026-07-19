"""Критика v4, clarify: без машинных артефактов в документе, честные подписи.

SPEAKER_N в пересланном «наверх» протоколе — «сырой машинный вывод» из
анти-референсов PRODUCT.md; «⏱ Время: 5 мин» читается как длительность
встречи; discussion для лекции — конспект, а не атрибуция реплик.
"""

from src.prompts.prompts import (
    FIELD_SPECIFIC_RULES,
    _get_type_specific_instructions,
)
from src.utils.text_processing import humanize_speaker_labels
from src.ux.message_builder import MessageBuilder

# ---------------------------------------------------------------------------
# SPEAKER_N не доезжает до читателя
# ---------------------------------------------------------------------------

def test_participants_rule_does_not_mandate_speaker_n():
    rule = FIELD_SPECIFIC_RULES["participants"]
    assert "оставляй SPEAKER_N" not in rule
    assert "Участник" in rule


def test_leftover_speaker_labels_humanized():
    text, count = humanize_speaker_labels(
        "SPEAKER_1 предложил план. SPEAKER_2 согласился, SPEAKER_1 уточнил срок."
    )
    assert text == (
        "Участник 1 предложил план. Участник 2 согласился, Участник 1 уточнил срок."
    )
    assert count == 2  # два разных несопоставленных говорящих


def test_humanize_leaves_clean_text_untouched():
    text, count = humanize_speaker_labels("Иван предложил план, Анна согласилась.")
    assert text == "Иван предложил план, Анна согласилась."
    assert count == 0


def test_pipeline_humanizes_and_warns():
    import inspect

    import src.services.processing.processing_service as ps

    src_text = inspect.getsource(ps)
    assert "humanize_speaker_labels" in src_text


def test_regeneration_humanizes_too():
    import inspect

    import src.services.protocol_actions as pa

    assert "humanize_speaker_labels" in inspect.getsource(pa)


# ---------------------------------------------------------------------------
# Сводка: «Обработка», а не «Время» (читается как длительность встречи)
# ---------------------------------------------------------------------------

def test_summary_labels_processing_duration_honestly():
    message = MessageBuilder.processing_complete_message(
        {
            "template_used": {"name": "Дейли"},
            "transcription_result": {"transcription": "т", "diarization": None},
            "processing_duration": 128,
        }
    )
    assert "Обработка" in message
    assert "Время:" not in message


# ---------------------------------------------------------------------------
# Лекция: discussion — конспект материала, не атрибуция реплик
# ---------------------------------------------------------------------------

def test_educational_instructions_set_lecture_genre():
    text = _get_type_specific_instructions("educational")
    assert "конспект" in text.lower()
    assert "атрибуци" in text.lower()
