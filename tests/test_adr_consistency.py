"""ADR-0001 ссылается на реально существующий стриппер эмодзи.

Единый проход снятия эмодзи называется `strip_emoji`; точечного
`strip_heading_emoji` в коде нет (см. test_pdf_heading_emoji).
"""

from pathlib import Path

_ADR = Path(__file__).resolve().parents[1] / "docs" / "adr" / "0001-protocol-channel-rendering.md"


def test_adr_0001_references_existing_stripper():
    text = _ADR.read_text(encoding="utf-8")
    assert "strip_heading_emoji" not in text
    assert "strip_emoji" in text
