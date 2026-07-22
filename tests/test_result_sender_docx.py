"""Доставка протокола файлом .docx (Word) и живучий фолбэк при сбое рендера."""

import io

import pytest
from docx import Document

from src.services import result_sender


def _capture_documents(monkeypatch):
    """Подменить отправку документа, вернуть список пойманных (filename, bytes)."""
    captured = []

    async def fake_send_document(bot, chat_id, **kwargs):
        input_file = kwargs["document"]
        with open(input_file.path, "rb") as f:
            captured.append((input_file.filename, f.read()))
        return object()

    monkeypatch.setattr(result_sender, "safe_send_document", fake_send_document)
    return captured


@pytest.mark.asyncio
async def test_docx_mode_delivers_word_document(monkeypatch):
    captured = _capture_documents(monkeypatch)

    ok = await result_sender.send_protocol_file(
        object(), 1,
        "# Планёрка\n\n## ✅ Решения\n1. Запускаем бету\n",
        "meeting.mp3", "docx",
    )

    assert ok is True
    assert len(captured) == 1
    filename, data = captured[0]
    assert filename.endswith(".docx")
    # Доставлен настоящий .docx: открывается python-docx'ом, стили Word на месте.
    doc = Document(io.BytesIO(data))
    assert any(p.style.name == "List Number" for p in doc.paragraphs)


@pytest.mark.asyncio
async def test_docx_render_failure_falls_back_to_md(monkeypatch):
    captured = _capture_documents(monkeypatch)

    async def exploding_render(protocol_text):
        raise RuntimeError("docx render failed")

    monkeypatch.setattr(
        "src.services.protocol_render.docx_renderer.convert_protocol_to_docx_async",
        exploding_render,
    )

    ok = await result_sender.send_protocol_file(
        object(), 1, "# Протокол\n\n## ✅ Решения\n1. Ок\n", "meeting.mp3", "docx",
    )

    assert ok is True
    assert len(captured) == 1
    filename, data = captured[0]
    # Рендер упал — вместо тишины уходит канонический .md.
    assert filename.endswith(".md")
    assert data.decode("utf-8").startswith("# Протокол")
