"""Входные данные встречи: то, что генерация протокола знает о встрече помимо записи.

Один неизменяемый объект вместо россыпи именованных аргументов генератора.
Тесты — через публичный интерфейс объекта (конструктор из запроса на обработку и
представления для промпта); что эти представления доходят до модели байт-в-байт,
держит `test_generation_prompts_characterization.py`.
"""
import dataclasses

import pytest

from src.llm import MeetingInputs
from src.models.processing import ProcessingRequest


def _request(**fields) -> ProcessingRequest:
    return ProcessingRequest(file_name="a.mp3", llm_provider="openai", user_id=1, **fields)


def test_built_from_request_carries_what_the_generator_reads():
    """Из запроса берутся участники, повестка, проекты и сопоставление; тип — от вызывающего."""
    meeting = MeetingInputs.from_request(
        _request(
            participants_list=[{"name": "Анна Смирнова", "role": "Аналитик"}],
            meeting_agenda="1. Релиз",
            project_list="Сорока",
            speaker_mapping={"SPEAKER_1": "Анна Смирнова"},
        ),
        meeting_type="status",
    )

    assert [dict(p) for p in meeting.participants] == [{"name": "Анна Смирнова", "role": "Аналитик"}]
    assert meeting.agenda == "1. Релиз"
    assert meeting.projects == "Сорока"
    assert dict(meeting.speaker_mapping) == {"SPEAKER_1": "Анна Смирнова"}
    assert meeting.meeting_type == "status"


def test_later_changes_to_the_request_do_not_leak_in():
    """Объект неизменяем: правка запроса после сборки и присваивание полю его не меняют."""
    request = _request(
        participants_list=[{"name": "Анна Смирнова", "role": "Аналитик"}],
        speaker_mapping={"SPEAKER_1": "Анна Смирнова"},
    )
    meeting = MeetingInputs.from_request(request)

    request.participants_list[0]["role"] = "Директор"
    request.speaker_mapping["SPEAKER_2"] = "Борис"

    assert dict(meeting.participants[0]) == {"name": "Анна Смирнова", "role": "Аналитик"}
    assert dict(meeting.speaker_mapping) == {"SPEAKER_1": "Анна Смирнова"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        meeting.agenda = "другая"


def test_participants_for_prompt_lists_short_names_with_roles():
    """Строка участников для промпта: «- Имя Фамилия (роль)», отчество отброшено, без роли — только имя."""
    meeting = MeetingInputs.from_request(_request(participants_list=[
        {"name": "Тимченко Алексей Александрович", "role": "Руководитель"},
        {"name": "Анна Смирнова", "role": ""},
        {"name": "Борис"},
    ]))

    assert meeting.participants_for_prompt() == (
        "- Алексей Тимченко (Руководитель)\n- Анна Смирнова\n- Борис"
    )


@pytest.mark.parametrize("participants", [None, []])
def test_participants_for_prompt_says_not_provided_when_nobody_is_known(participants):
    """Участников нет (не передан список или он пуст) — модель видит «Не предоставлен»."""
    meeting = MeetingInputs.from_request(_request(participants_list=participants))

    assert meeting.participants_for_prompt() == "Не предоставлен"


@pytest.mark.parametrize(
    ("meeting_type", "speaker_mapping", "settled"),
    [
        ("technical", {"SPEAKER_1": "Анна Смирнова"}, True),
        ("technical", None, False),
        ("technical", {}, False),
        (None, {"SPEAKER_1": "Анна Смирнова"}, False),
        (None, None, False),
    ],
)
def test_analysis_is_settled_only_when_type_and_mapping_are_both_known(
    meeting_type, speaker_mapping, settled,
):
    """ЭТАП 1 анализа не нужен, только когда известны и тип встречи, и сопоставление спикеров."""
    meeting = MeetingInputs.from_request(
        _request(speaker_mapping=speaker_mapping), meeting_type=meeting_type,
    )

    assert meeting.analysis_settled is settled
