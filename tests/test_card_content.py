"""Семантическое содержимое карточки и его рендер (ADR-0005).

Экран описывается семантически — заголовком и строками спикеров с цитатами, —
а разметку добавляет рендер: Telegram HTML для чата (экранирование только «&»,
«<», «>», как тело протокола в ADR-0001) и plain-страховка, которая несёт то же
содержимое без тегов. Тесты проверяют содержимое, а не экранирование.
"""

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))

from src.ux.card_content import (  # noqa: E402
    _SEPARATOR,
    MappingCard,
    PlainCard,
    SpeakerRow,
)


def test_quote_special_chars_survive_html_and_plain():
    """Цитата со спецсимволами <, &, _ рендерится в валидный HTML без потери
    символов; plain-страховка — тот же текст без тегов и без экранирования."""
    card = MappingCard(
        header="Проверьте сопоставление спикеров",
        rows=(
            SpeakerRow(
                speaker_id="SPEAKER_1",
                display_name="Иван",
                quote="a < b & c_d",
            ),
        ),
    )

    html = card.to_html()
    plain = card.to_plain()

    # HTML экранирует только &, <, >; подчёркивание остаётся буквальным
    assert "a &lt; b &amp; c_d" in html
    assert "<b>" in html  # жирный заголовок/спикер — разметка на месте

    # plain несёт тот же текст цитаты без экранирования и без тегов
    assert "a < b & c_d" in plain
    assert "&lt;" not in plain
    assert "<b>" not in plain


def test_mapped_and_unmapped_rows_are_labelled():
    """Сопоставленный спикер подписан именем с ✓; несопоставленный — «Не
    определен ❓». Спикер жирный в HTML, буквальный в plain."""
    card = MappingCard(
        header="Проверьте сопоставление спикеров",
        rows=(
            SpeakerRow(speaker_id="SPEAKER_1", display_name="Иван"),
            SpeakerRow(speaker_id="SPEAKER_2", display_name=None),
        ),
    )

    html = card.to_html()
    plain = card.to_plain()

    assert "<b>SPEAKER_1</b> → Иван ✓" in html
    assert "<b>SPEAKER_2</b> → Не определен ❓" in html
    assert "SPEAKER_1 → Иван ✓" in plain
    assert "SPEAKER_2 → Не определен ❓" in plain


def test_hint_renders_before_separator_in_html_and_plain():
    """Опциональная подсказка (nudge о последствиях) — строка перед разделителем:
    в HTML экранирована, в plain та же без тегов; читателю видно следствие."""
    hint = "Неназванные спикеры попадут в протокол как «Участник N»"
    card = MappingCard(
        header="Назовите спикеров (по желанию)",
        rows=(SpeakerRow(speaker_id="SPEAKER_1", display_name=None),),
        hint=hint,
    )

    html = card.to_html()
    plain = card.to_plain()

    assert hint in plain
    assert hint in html  # экранирование не трогает «», буквы, N
    # подсказка стоит перед разделителем — внизу карточки
    assert html.index("Участник N") < html.index(_SEPARATOR)
    assert plain.index("Участник N") < plain.index(_SEPARATOR)


def test_no_hint_keeps_card_layout_unchanged():
    """Без подсказки лишних строк нет: хвост — спикер, пустая строка, разделитель."""
    card = MappingCard(
        header="Проверьте сопоставление спикеров",
        rows=(SpeakerRow(speaker_id="SPEAKER_1", display_name="Иван"),),
    )

    assert card.to_plain().endswith("SPEAKER_1 → Иван ✓\n\n" + _SEPARATOR)


def test_plain_card_escapes_html_but_keeps_raw_plain():
    """PlainCard экранирует спецсимволы для HTML, а plain-страховку отдаёт как есть."""
    card = PlainCard(text="Отправьте имя для <SPEAKER_1> сообщением")

    assert card.to_html() == "Отправьте имя для &lt;SPEAKER_1&gt; сообщением"
    assert card.to_plain() == "Отправьте имя для <SPEAKER_1> сообщением"
