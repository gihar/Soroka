"""Критика v11: оговорка о подставленной дате едет вместе с документом.

Комментарий к ``_document_notes`` объяснял, что оговорки перенесены в сводку
именно потому, что отдельный пузырь «в режимах pdf/docx оставался в чате и с
файлом не ехал». Но в этих режимах сводка — тоже отдельное сообщение:
``_send_summary_message`` шлёт её, ``send_protocol_body`` отдельно шлёт файл.
Пометка «Дата в шапке — день обработки» оставалась в чате.

Руководитель получал PDF, где датой встречи стоит день обработки, без единого
признака этого. Про «Участник N» было сделано правильно — та сноска вписана в
тело документа; дата теперь тоже.
"""

import pytest

from src.utils.text_processing import with_assumed_date_note

_PROTOCOL = (
    "# Планёрка\n"
    "**Дата:** 30 июля 2026\n"
    "\n"
    "## Решения\n"
    "Запускаем.\n"
)


# ---------------------------------------------------------------------------
# Пометка в теле документа
# ---------------------------------------------------------------------------


def test_note_lands_in_the_document():
    assert "день обработки" in with_assumed_date_note(_PROTOCOL)


def test_note_stands_before_the_first_section():
    """«Дата» — реквизит шапки: сноска в конце опоздает."""
    result = with_assumed_date_note(_PROTOCOL)
    assert result.index("день обработки") < result.index("## Решения")


def test_header_survives():
    result = with_assumed_date_note(_PROTOCOL)
    assert result.startswith("# Планёрка\n**Дата:** 30 июля 2026")


def test_body_survives():
    assert "## Решения\nЗапускаем." in with_assumed_date_note(_PROTOCOL)


def test_note_is_not_doubled():
    once = with_assumed_date_note(_PROTOCOL)
    assert with_assumed_date_note(once) == once


def test_protocol_without_sections_still_gets_the_note():
    assert "день обработки" in with_assumed_date_note("# Планёрка\nТекст.\n")


def test_input_is_not_mutated():
    original = str(_PROTOCOL)
    with_assumed_date_note(_PROTOCOL)
    assert _PROTOCOL == original


def test_note_is_italic_like_the_speaker_note():
    """Обе сноски документа выглядят одинаково — это один класс оговорки."""
    from src.utils.text_processing import _UNMAPPED_NOTE

    note = with_assumed_date_note(_PROTOCOL)
    line = next(ln for ln in note.splitlines() if "день обработки" in ln)
    assert line.startswith("_") and line.endswith("_")
    assert _UNMAPPED_NOTE.startswith("_")


# ---------------------------------------------------------------------------
# Разделение по каналам доставки
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["file", "pdf", "docx"])
def test_file_modes_carry_the_note_in_the_body(mode):
    from src.services.result_sender import protocol_text_for_delivery

    text = protocol_text_for_delivery(_PROTOCOL, date_is_assumed=True, output_mode=mode)

    assert "день обработки" in text


def test_messages_mode_leaves_the_body_alone():
    """В чат протокол едет вместе со сводкой — дублировать оговорку незачем."""
    from src.services.result_sender import protocol_text_for_delivery

    text = protocol_text_for_delivery(
        _PROTOCOL, date_is_assumed=True, output_mode="messages"
    )

    assert text == _PROTOCOL


def test_known_date_never_adds_a_note():
    from src.services.result_sender import protocol_text_for_delivery

    for mode in ("messages", "file", "pdf", "docx"):
        assert protocol_text_for_delivery(
            _PROTOCOL, date_is_assumed=False, output_mode=mode
        ) == _PROTOCOL


def test_summary_note_only_for_messages():
    from src.ux.message_builder import MessageBuilder

    in_chat = MessageBuilder.processing_complete_message({
        "date_is_assumed": True, "protocol_output_mode": "messages",
    })
    as_file = MessageBuilder.processing_complete_message({
        "date_is_assumed": True, "protocol_output_mode": "pdf",
    })

    assert "Дата в шапке" in in_chat
    assert "Дата в шапке" not in as_file, "в файловых режимах оговорка в документе"


def test_summary_defaults_to_showing_the_note():
    """Режим не передан — ведём себя как в чате, оговорку не теряем."""
    from src.ux.message_builder import MessageBuilder

    assert "Дата в шапке" in MessageBuilder.processing_complete_message({
        "date_is_assumed": True,
    })


def test_pipeline_warnings_are_shown_in_every_mode():
    """Предупреждения конвейера — не про шапку, их канал не меняется."""
    from src.ux.message_builder import MessageBuilder

    summary = MessageBuilder.processing_complete_message({
        "warnings": ["Запись была сжата"], "protocol_output_mode": "pdf",
    })

    assert "Запись была сжата" in summary
