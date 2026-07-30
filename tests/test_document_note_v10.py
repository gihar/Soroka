"""Критика v10: пояснение про «Участник N» едет внутри документа.

Пояснение жило отдельным пузырём в чате. В режимах PDF/Word пересылают файл —
и оно отваливалось ровно тогда, когда нужнее всего: руководство получало
«Участник 2 — подготовит смету к пятнице» без всякого объяснения, кто это.

Место пометки — сразу под шапкой: читатель встречает «Участник 2» в середине
документа, и объяснение в конце опаздывает.
"""

from src.utils.text_processing import (
    humanize_speaker_labels_for_reader,
    with_unmapped_speakers_note,
)

_NOTE_MARK = "Участник N"


def test_note_is_inserted_under_the_header():
    text = (
        "# Планёрка\n"
        "**Дата:** 27 июля 2026\n"
        "\n"
        "## ✅ Решения\n"
        "Участник 2 готовит смету.\n"
    )
    out = with_unmapped_speakers_note(text, unmapped_count=1)
    lines = out.splitlines()

    assert lines[0] == "# Планёрка"
    assert lines[1] == "**Дата:** 27 июля 2026"
    # Пометка стоит до первой секции, а не после неё.
    note_index = next(i for i, line in enumerate(lines) if _NOTE_MARK in line)
    section_index = next(i for i, line in enumerate(lines) if line.startswith("## "))
    assert note_index < section_index


def test_note_is_absent_when_everyone_is_mapped():
    text = "# Планёрка\n**Дата:** 27 июля 2026\n\n## ✅ Решения\nИван готовит смету.\n"
    assert with_unmapped_speakers_note(text, unmapped_count=0) == text


def test_note_survives_a_protocol_without_header():
    text = "## ✅ Решения\nУчастник 1 готовит смету.\n"
    out = with_unmapped_speakers_note(text, unmapped_count=1)
    assert _NOTE_MARK in out
    assert "## ✅ Решения" in out


def test_note_is_not_duplicated():
    text = "# Планёрка\n\n## ✅ Решения\nУчастник 1.\n"
    once = with_unmapped_speakers_note(text, unmapped_count=1)
    twice = with_unmapped_speakers_note(once, unmapped_count=1)
    assert twice.count(_NOTE_MARK) == 1


def test_note_does_not_mutate_input():
    text = "# Планёрка\n\n## ✅ Решения\nУчастник 1.\n"
    original = text
    with_unmapped_speakers_note(text, unmapped_count=1)
    assert text == original


def test_reader_pass_puts_the_note_into_the_document():
    """Единая точка обоих путей генерации обязана вписать пометку в текст."""
    warnings: list = []
    out = humanize_speaker_labels_for_reader(
        "# Планёрка\n\n## ✅ Решения\nSPEAKER_2 готовит смету.\n", warnings
    )

    assert "Участник 2 готовит смету." in out
    assert _NOTE_MARK in out, "пояснение обязано ехать внутри документа"
    # Сводка в чате тоже сохраняет свою пометку — она видна до открытия файла.
    assert warnings


def test_reader_pass_stays_silent_when_all_speakers_are_named():
    warnings: list = []
    out = humanize_speaker_labels_for_reader(
        "# Планёрка\n\n## ✅ Решения\nИван готовит смету.\n", warnings
    )

    assert _NOTE_MARK not in out
    assert warnings == []
